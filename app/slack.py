"""Slack delivery via incoming webhooks (Block Kit messages)."""

import logging

import requests

from app.digest import _truncate_authors
from app.models import LabPaper, Paper

logger = logging.getLogger(__name__)

_MAX_BLOCKS = 50  # Slack limit per message
_MAX_TEXT = 2900  # section text limit is 3000 chars


def _escape(text: str) -> str:
    """Escape the three characters Slack mrkdwn treats as control chars."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _paper_block(paper: LabPaper) -> dict:
    """One section block per paper: linked title, authors, venue, date, context."""
    title = _escape(paper.title or "Untitled")
    title_line = f"*<{paper.url}|{title}>*" if paper.url else f"*{title}*"

    meta = [_escape(_truncate_authors(paper.authors))]
    if paper.journal:
        meta.append(f"_{_escape(paper.journal)}_")
    if paper.published_date:
        meta.append(paper.published_date)
    lines = [title_line, " · ".join(meta)]

    if paper.kind == "authored" and paper.lab_authors:
        lines.append(f"Lab: {_escape(', '.join(paper.lab_authors))}")
    if paper.kind == "citing" and paper.cited_lab_works:
        titles = [w["title"] for w in paper.cited_lab_works]
        cited = "; ".join(_escape(t) for t in titles[:3])
        more = len(titles) - 3
        lines.append(f"Cites: _{cited}_" + (f" (+{more} more)" if more > 0 else ""))

    text = "\n".join(lines)
    if len(text) > _MAX_TEXT:
        text = text[: _MAX_TEXT - 1] + "…"
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def build_messages(lab_name: str, authored: list[LabPaper], citing: list[LabPaper]) -> list[dict]:
    """Build Slack payloads, split into several messages if over the block limit."""
    summary = f"{lab_name} watch: {len(authored)} new lab papers, {len(citing)} new citing papers"
    blocks: list[dict] = [{"type": "header", "text": {"type": "plain_text", "text": summary[:150]}}]

    for heading, papers in (("New from the lab", authored), ("Citing the lab", citing)):
        if not papers:
            continue
        blocks.append({"type": "divider"})
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*{heading}*"}})
        blocks.extend(_paper_block(p) for p in papers)

    return [
        {"text": summary, "blocks": blocks[i : i + _MAX_BLOCKS]}
        for i in range(0, len(blocks), _MAX_BLOCKS)
    ]


_TIER_LABEL = {
    "confirmed": "Confirmed match",
    "mentioned": "Mentioned in full text",
    "keyword_only": "Keyword match",
}


def _digest_paper_block(paper: Paper) -> dict:
    """One section block per discovery paper: title, meta, score, and the
    evidence tier so the ranking isn't just an opaque number — same
    transparency as the keyword-vs-full-text evidence the spine-generic
    analysis gave.
    """
    title = _escape(paper.title or "Untitled")
    title_line = f"*<{paper.url}|{title}>*" if paper.url else f"*{title}*"

    meta = [_escape(_truncate_authors(paper.authors))]
    if paper.journal:
        meta.append(f"_{_escape(paper.journal)}_")
    if paper.published_date:
        meta.append(paper.published_date)
    lines = [title_line, " · ".join(meta), f"Score: {paper.score:.0f}"]

    tier_label = _TIER_LABEL.get(paper.evidence_tier, "Keyword match")
    if paper.evidence_tier in ("confirmed", "mentioned") and paper.evidence_snippet:
        snippet = _escape(paper.evidence_snippet)
        if len(snippet) > 220:
            snippet = snippet[:220] + "…"
        lines.append(f"{tier_label}: _“…{snippet}…”_")
    else:
        lines.append(tier_label)

    text = "\n".join(lines)
    if len(text) > _MAX_TEXT:
        text = text[: _MAX_TEXT - 1] + "…"
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def build_digest_messages(topic_results: list[tuple[str, list[Paper]]]) -> list[dict]:
    """Build Slack payloads for the discovery digest (distinct from
    build_messages, which is lab-watch's authored/citing format).
    """
    total = sum(len(papers) for _, papers in topic_results)
    summary = f"Paper-Watch digest: {total} paper{'s' if total != 1 else ''}"
    blocks: list[dict] = [{"type": "header", "text": {"type": "plain_text", "text": summary[:150]}}]

    for topic_name, papers in topic_results:
        if not papers:
            continue
        blocks.append({"type": "divider"})
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*{topic_name}*"}})
        blocks.extend(_digest_paper_block(p) for p in papers)

    return [
        {"text": summary, "blocks": blocks[i : i + _MAX_BLOCKS]}
        for i in range(0, len(blocks), _MAX_BLOCKS)
    ]


def build_citation_pointer_message(lab_name: str, count: int, url: str) -> list[dict]:
    """One lightweight payload pointing to the citations digest page (not posted in detail yet)."""
    plural = "s" if count != 1 else ""
    text = f"*{_escape(lab_name)} watch:* {count} new paper{plural} cite the lab this week — <{url}|see them>"
    return [{"text": text, "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]}]


def post_to_slack(webhook_url: str, messages: list[dict]) -> None:
    """Send each payload to the webhook. Raises on HTTP errors."""
    for payload in messages:
        resp = requests.post(webhook_url, json=payload, timeout=15)
        resp.raise_for_status()
    logger.info("Posted %d Slack message(s)", len(messages))
