"""Slack delivery via incoming webhooks (Block Kit messages)."""

import logging

import requests

from app.digest import _truncate_authors
from app.models import LabPaper

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
    if paper.kind == "citing" and paper.cited_lab_titles:
        cited = "; ".join(_escape(t) for t in paper.cited_lab_titles[:3])
        more = len(paper.cited_lab_titles) - 3
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


def post_to_slack(webhook_url: str, messages: list[dict]) -> None:
    """Send each payload to the webhook. Raises on HTTP errors."""
    for payload in messages:
        resp = requests.post(webhook_url, json=payload, timeout=15)
        resp.raise_for_status()
    logger.info("Posted %d Slack message(s)", len(messages))
