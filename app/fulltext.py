"""Full-text verification for borderline-scored papers.

Keyword matching on title+abstract alone has bad recall — proven directly
this session: full-text phrase search found up to 23x more true matches than
abstract-only search on the same question. This module re-checks a paper's
*actual* full text (Methods section included) instead of trusting the
abstract, for papers whose keyword score isn't already decisive either way.

Pipeline per paper: resolve a PMCID via Europe PMC (cheap, no download) →
fetch its full-text XML if available → otherwise resolve an open-access copy
via Unpaywall and extract text from the PDF/HTML. Every step fails open
(returns None) rather than raising, since this runs inline in the scoring
pass and a slow/broken paper shouldn't break the whole run.
"""

import logging
import re
import subprocess
import tempfile
from pathlib import Path

import requests

from app.models import Paper, Topic

logger = logging.getLogger(__name__)

_EPMC_SEARCH = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
_EPMC_FULLTEXT = "https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
_UNPAYWALL_API = "https://api.unpaywall.org/v2/{doi}"
_TIMEOUT = 20
_SNIPPET_PAD = 150
_USAGE_VERBS = ("used", "acquired", "downloaded", "applied", "dataset", "protocol", "obtained")


def _get_unpaywall_email() -> str:
    import os
    return os.getenv("UNPAYWALL_EMAIL") or os.getenv("OPENALEX_EMAIL") or "paperwatch@example.com"


def _strip_html(text: str) -> str:
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _extract_pdf_text(content: bytes) -> str | None:
    """Write PDF bytes to a temp file and shell out to pdftotext (poppler-utils)."""
    try:
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = Path(tmp) / "doc.pdf"
            pdf_path.write_bytes(content)
            result = subprocess.run(
                ["pdftotext", "-layout", str(pdf_path), "-"],
                capture_output=True, timeout=30,
            )
            text = result.stdout.decode("utf-8", errors="ignore")
            return re.sub(r"\s+", " ", text).strip() or None
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        logger.warning("pdftotext extraction failed: %s", exc)
        return None


def _resolve_pmcid(doi: str) -> str | None:
    """Look up a DOI's PMCID via Europe PMC, if it has one."""
    try:
        resp = requests.get(
            _EPMC_SEARCH,
            params={"query": f"DOI:{doi}", "format": "json"},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        results = resp.json().get("resultList", {}).get("result", [])
        return results[0].get("pmcid") if results else None
    except Exception as exc:
        logger.warning("Europe PMC PMCID lookup failed for %s: %s", doi, exc)
        return None


def _fetch_epmc_fulltext(pmcid: str) -> str | None:
    try:
        resp = requests.get(_EPMC_FULLTEXT.format(pmcid=pmcid), timeout=_TIMEOUT)
        if resp.status_code != 200 or not resp.text.strip().startswith("<"):
            return None
        return _strip_html(resp.text)
    except Exception as exc:
        logger.warning("Europe PMC full-text fetch failed for %s: %s", pmcid, exc)
        return None


def find_oa_copy(doi: str) -> str | None:
    """Return the best open-access URL for a DOI via Unpaywall, or None."""
    try:
        resp = requests.get(
            _UNPAYWALL_API.format(doi=doi),
            params={"email": _get_unpaywall_email()},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("is_oa"):
            return None
        best = data.get("best_oa_location") or {}
        return best.get("url_for_pdf") or best.get("url")
    except Exception as exc:
        logger.warning("Unpaywall lookup failed for %s: %s", doi, exc)
        return None


def fetch_fulltext(doi: str) -> str | None:
    """Best-effort full text for a DOI: Europe PMC first, then an OA mirror.

    Returns None if nothing is retrievable — treated as "couldn't verify",
    not as a negative signal.
    """
    if not doi:
        return None

    pmcid = _resolve_pmcid(doi)
    if pmcid:
        text = _fetch_epmc_fulltext(pmcid)
        if text:
            return text

    oa_url = find_oa_copy(doi)
    if not oa_url:
        return None

    try:
        resp = requests.get(
            oa_url, timeout=30, allow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (paperwatch research tool)"},
        )
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        if "pdf" in content_type or oa_url.lower().endswith(".pdf"):
            return _extract_pdf_text(resp.content)
        return _strip_html(resp.text)
    except Exception as exc:
        logger.warning("OA fetch failed for %s (%s): %s", doi, oa_url, exc)
        return None


def _find_snippet(text: str, terms: list[str]) -> tuple[str | None, bool]:
    """Find the first term match and return (context window, near a usage verb)."""
    low = text.lower()
    for term in terms:
        idx = low.find(term.lower())
        if idx == -1:
            continue
        start = max(0, idx - _SNIPPET_PAD)
        end = min(len(text), idx + len(term) + _SNIPPET_PAD)
        snippet = text[start:end].strip()
        near_usage_verb = any(v in snippet.lower() for v in _USAGE_VERBS)
        return snippet, near_usage_verb
    return None, False


def verify_topic_usage(text: str, topic: Topic) -> tuple[str, str | None]:
    """Classify how a paper's full text actually relates to a topic.

    Returns (tier, snippet):
      "confirmed" — a topic term appears near a usage verb (used/acquired/
                    dataset/protocol/...), i.e. this looks like real use,
                    not just a passing mention
      "mentioned" — a topic term appears, but not near a usage verb
      "keyword_only" — no full-text match at all (same as not having checked)
    """
    if not text:
        return "keyword_only", None

    terms = list(topic.include_any) + list(topic.include_all)
    snippet, near_usage_verb = _find_snippet(text, terms)
    if snippet is None:
        return "keyword_only", None
    return ("confirmed" if near_usage_verb else "mentioned"), snippet


_SCORE_BUMP = {"confirmed": 25.0, "mentioned": 10.0}


def apply_evidence_pass(papers: list[Paper], topic: Topic, *, evidence_band: tuple[float, float], max_checks: int) -> None:
    """Full-text-verify papers whose keyword score alone didn't settle it.

    Mutates each checked paper's evidence_tier/evidence_snippet in place, and
    bumps its score on a "confirmed" or "mentioned" result. Bounded by
    max_checks so one run can't rack up unbounded Unpaywall/Europe PMC calls.
    Papers without a DOI, or outside the band, keep the default
    "keyword_only" tier set by app/scoring.py — not every paper needs this,
    only the ones where the keyword score alone can't be trusted either way.
    """
    low, high = evidence_band
    candidates = [p for p in papers if p.doi and low <= p.score <= high]
    # Highest-scoring borderline papers first — they're the most likely wins
    candidates.sort(key=lambda p: p.score, reverse=True)

    for paper in candidates[:max_checks]:
        text = fetch_fulltext(paper.doi)
        tier, snippet = verify_topic_usage(text, topic) if text else ("keyword_only", None)
        paper.evidence_tier = tier
        paper.evidence_snippet = snippet
        bump = _SCORE_BUMP.get(tier)
        if bump:
            paper.score = round(min(paper.score + bump, 95.0), 1)
