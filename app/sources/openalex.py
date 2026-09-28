"""OpenAlex fetcher for lab-authored papers and papers citing the lab.

A work counts as a lab paper if any of these match:
  - an author's ORCID (covers all of OpenAlex's split profiles for that person)
  - an explicit OpenAlex author ID (for people without an ORCID)
  - an affiliation keyword like "NeuroPoly" in the raw affiliation strings
    (catches members nobody listed, e.g. new students)
"""

import os
import re
import time
import unicodedata
from datetime import datetime, timedelta, timezone

import requests

from app.models import LabConfig, LabPaper

_WORKS_URL = "https://api.openalex.org/works"
_AUTHORS_URL = "https://api.openalex.org/authors"
_PER_PAGE = 200  # OpenAlex max
_OR_CHUNK = 50  # values per OR filter (API allows 100; keeps URLs short)
_SLEEP = 0.2
_MAX_AFFILIATION_LEN = 300  # longer raw strings are journal-lumped author lists
# Reported works only; drops Zenodo datasets/software releases, errata, etc.
_REPORT_TYPES = "type:article|preprint|review|conference-paper|book-chapter"
_WORK_FIELDS = (
    "id,doi,title,publication_date,authorships,primary_location,"
    "abstract_inverted_index,referenced_works"
)


def _base_params() -> dict:
    """Auth / polite-pool params, both optional."""
    params = {}
    if key := os.getenv("OPENALEX_API_KEY"):
        params["api_key"] = key
    if email := os.getenv("OPENALEX_EMAIL"):
        params["mailto"] = email
    return params


def _short_id(openalex_url: str | None) -> str:
    """https://openalex.org/W123 → W123 (also works on bare IDs)."""
    return (openalex_url or "").rstrip("/").rsplit("/", 1)[-1]


def _norm_orcid(orcid: str | None) -> str:
    """https://orcid.org/0000-... → 0000-..."""
    return (orcid or "").rstrip("/").rsplit("/", 1)[-1]


def _norm_name(name: str) -> str:
    """Fold accents, case, hyphen variants: 'Jan Valošek' == 'jan valosek'."""
    spaced = re.sub(r"[\W\d_]+", " ", name)  # before ASCII folding, or U+2010 hyphens vanish
    ascii_name = unicodedata.normalize("NFKD", spaced).encode("ascii", "ignore").decode()
    return " ".join(ascii_name.lower().split())


def _chunks(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _lab_filters(cfg: LabConfig) -> list[str]:
    """Build one OpenAlex filter per match type (ORs across keys aren't allowed)."""
    orcids = [_norm_orcid(a.orcid) for a in cfg.authors if a.orcid]
    oa_ids = [_short_id(i) for a in cfg.authors for i in a.openalex_ids]
    filters = [f"author.orcid:{'|'.join(c)}" for c in _chunks(orcids, _OR_CHUNK)]
    filters += [f"authorships.author.id:{'|'.join(c)}" for c in _chunks(oa_ids, _OR_CHUNK)]
    filters += [f"raw_affiliation_strings.search:{kw}" for kw in cfg.affiliations]
    return filters


def _get_all(filter_str: str, select: str) -> list[dict]:
    """Page through every work matching a filter using cursor pagination."""
    results: list[dict] = []
    cursor = "*"
    while cursor:
        params = {
            **_base_params(),
            "filter": filter_str,
            "select": select,
            "per_page": _PER_PAGE,
            "cursor": cursor,
        }
        resp = requests.get(_WORKS_URL, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        results.extend(data.get("results", []))
        cursor = data.get("meta", {}).get("next_cursor")
        time.sleep(_SLEEP)
    return results


def _abstract_from_index(inverted: dict | None) -> str | None:
    """Rebuild plain text from OpenAlex's abstract_inverted_index."""
    if not inverted:
        return None
    positions = [(i, word) for word, idxs in inverted.items() for i in idxs]
    return " ".join(word for _, word in sorted(positions)) or None


def _lab_lookups(cfg: LabConfig) -> tuple[dict, dict, dict, list[str]]:
    by_orcid = {_norm_orcid(a.orcid): a.name for a in cfg.authors if a.orcid}
    by_id = {_short_id(i): a.name for a in cfg.authors for i in a.openalex_ids}
    by_name = {_norm_name(a.name): a.name for a in cfg.authors}
    keywords = [kw.lower() for kw in cfg.affiliations]
    return by_orcid, by_id, by_name, keywords


def _lab_member_name(authorship: dict, by_orcid: dict, by_id: dict, by_name: dict, keywords: list[str]) -> str | None:
    """Match a single authorship against the lab roster.

    Tried in order: ORCID / OpenAlex ID, then name (the work is already known
    to be a lab paper, and OpenAlex often attaches authorships to a stray
    profile without the ORCID), then affiliation keyword. Very long affiliation
    strings are ignored: some journals lump every author's affiliation into one
    string, which would tag the whole author list.
    """
    author = authorship.get("author") or {}
    display = author.get("display_name") or ""
    name = (
        by_orcid.get(_norm_orcid(author.get("orcid")))
        or by_id.get(_short_id(author.get("id")))
        or by_name.get(_norm_name(display))
    )
    if not name and any(
        kw in s.lower()
        for s in authorship.get("raw_affiliation_strings") or []
        if len(s) <= _MAX_AFFILIATION_LEN
        for kw in keywords
    ):
        name = display
    return name


def _match_lab_authors(work: dict, cfg: LabConfig, alumni: frozenset = frozenset()) -> list[str]:
    """Return the names of CURRENT lab members on a work, in author-list order.

    Alumni matches (via any signal — ORCID, ID, name, or the affiliation-keyword
    fallback) are excluded: OpenAlex affiliation strings are stale by nature, so
    someone who left the lab can keep matching indefinitely otherwise. See
    app/sources/team_roster.py.
    """
    lookups = _lab_lookups(cfg)
    names: list[str] = []
    for authorship in work.get("authorships") or []:
        name = _lab_member_name(authorship, *lookups)
        if name and _norm_name(name) not in alumni and name not in names:
            names.append(name)
    return names


def _is_first_author_from_lab(work: dict, cfg: LabConfig, alumni: frozenset = frozenset()) -> bool:
    """True if the work was driven by the CURRENT lab.

    A current member leading it is the clear case. If the first author is an
    alumnus, it still counts if a CURRENT member also co-authored it (e.g. the
    supervising PI, on work published while that alumnus was still around) —
    otherwise a legitimately lab-led paper like AxonDeepSeg would lose its
    standing the moment its lead author graduated. It's only demoted when the
    alumnus's name is the *only* lab connection on the paper at all, which is
    the actual bug this guards against: their new work, after leaving, at a
    different institution, still carrying a stale "NeuroPoly" affiliation.
    """
    authorships = work.get("authorships") or []
    if not authorships:
        return False
    lookups = _lab_lookups(cfg)
    first_name = _lab_member_name(authorships[0], *lookups)
    if not first_name:
        return False
    if _norm_name(first_name) not in alumni:
        return True
    return any(
        (name := _lab_member_name(a, *lookups)) and _norm_name(name) not in alumni
        for a in authorships[1:]
    )


def _parse_work(work: dict, kind: str) -> LabPaper:
    """Convert an OpenAlex work dict into a LabPaper."""
    work_id = _short_id(work.get("id"))
    doi_url = work.get("doi")
    doi = doi_url.removeprefix("https://doi.org/") if doi_url else None
    location = work.get("primary_location") or {}
    source = location.get("source") or {}
    authors = [
        (a.get("author") or {}).get("display_name", "")
        for a in work.get("authorships") or []
    ]
    return LabPaper(
        kind=kind,
        source="openalex",
        source_id=f"openalex:{work_id}",
        title=work.get("title") or "",
        abstract=_abstract_from_index(work.get("abstract_inverted_index")),
        authors=[a for a in authors if a],
        published_date=work.get("publication_date"),
        journal=source.get("display_name"),
        doi=doi,
        url=doi_url or location.get("landing_page_url") or work.get("id"),
    )


def _since(days_back: int) -> str:
    return (datetime.now(timezone.utc).date() - timedelta(days=days_back)).isoformat()


_LAB_WORK_FIELDS = "id,title,authorships,publication_date"


def fetch_lab_works(cfg: LabConfig, alumni: frozenset = frozenset()) -> dict[str, dict]:
    """Return every work ever written by the lab, as
    {work_id: {title, authors, published_date, is_first_author}}.

    is_first_author distinguishes lab-led work from work where a lab member
    (often the PI) is just a co-author elsewhere — used to rank the citations
    digest so real lab output outranks high-citation-count noise. Works aren't
    dropped based on alumni status here (that would erase legitimate historical
    output like AxonDeepSeg from citation tracking); only is_first_author is
    alumni-aware, so a genuinely external post-departure paper simply doesn't
    get ranked as "lab-led" — see _is_first_author_from_lab.

    Not type-filtered: a paper citing the lab's software or dataset still counts.
    """
    works: dict[str, dict] = {}
    for f in _lab_filters(cfg):
        for w in _get_all(f, _LAB_WORK_FIELDS):
            authors = [
                (a.get("author") or {}).get("display_name", "") for a in w.get("authorships") or []
            ]
            works[_short_id(w["id"])] = {
                "title": w.get("title") or "",
                "authors": [a for a in authors if a],
                "published_date": w.get("publication_date"),
                "is_first_author": _is_first_author_from_lab(w, cfg, alumni=alumni),
            }
    return works


def fetch_lab_papers(cfg: LabConfig, days_back: int, alumni: frozenset = frozenset()) -> list[LabPaper]:
    """Fetch papers written by CURRENT lab members in the last `days_back` days.

    A paper is dropped entirely if only alumni matched — in this recent window,
    that's almost always someone's post-departure work at their new institution
    still carrying a stale "NeuroPoly" affiliation, not a new lab paper worth
    alerting on.

    Unlike the topic fetchers, errors propagate: a silent empty result would
    look like a quiet week instead of a failed run.
    """
    papers: dict[str, LabPaper] = {}
    for f in _lab_filters(cfg):
        filter_str = f"{f},{_REPORT_TYPES},from_publication_date:{_since(days_back)}"
        for work in _get_all(filter_str, _WORK_FIELDS):
            lab_authors = _match_lab_authors(work, cfg, alumni=alumni)
            if not lab_authors:
                continue
            paper = _parse_work(work, "authored")
            paper.lab_authors = lab_authors
            paper.is_first_author = _is_first_author_from_lab(work, cfg, alumni=alumni)
            papers[paper.source_id] = paper
    return list(papers.values())


def fetch_citing_papers(lab_works: dict[str, dict], days_back: int) -> list[LabPaper]:
    """Fetch recent papers citing any lab work, excluding the lab's own papers."""
    papers: dict[str, LabPaper] = {}
    since = _since(days_back)
    for chunk in _chunks(sorted(lab_works), _OR_CHUNK):
        filter_str = f"cites:{'|'.join(chunk)},{_REPORT_TYPES},from_publication_date:{since}"
        for work in _get_all(filter_str, _WORK_FIELDS):
            work_id = _short_id(work.get("id"))
            if work_id in lab_works:
                continue  # self-citation, already covered by fetch_lab_papers
            paper = papers.get(f"openalex:{work_id}") or _parse_work(work, "citing")
            cited_titles = {w["title"] for w in paper.cited_lab_works}
            for ref in work.get("referenced_works") or []:
                info = lab_works.get(_short_id(ref))
                if info and info["title"] not in cited_titles:
                    paper.cited_lab_works.append(info)
                    cited_titles.add(info["title"])
            papers[paper.source_id] = paper
    return list(papers.values())


def search_authors(name: str, limit: int = 10) -> list[dict]:
    """Search OpenAlex author profiles by name (to fill in config/lab.yaml)."""
    params = {
        **_base_params(),
        "search": name,
        "select": "id,display_name,orcid,works_count,last_known_institutions",
        "per_page": limit,
    }
    resp = requests.get(_AUTHORS_URL, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json().get("results", [])
