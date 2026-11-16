"""Static HTML digest page for the topic-based discovery pipeline.

Mirrors app/citations_page.py's shape and styling so both pages read as the
same product. The Slack bot only ever posts a link to this page (plus the
daily lab-paper reminder) — never the paper list itself. See CLAUDE.md.

Usage: called inline from app/main.py::run(), using the same topic_results
already computed in memory for that run (no DB re-query needed).
"""

import html
from datetime import datetime, timezone

from app.citations_page import _STYLE
from app.digest import _evidence_line, _truncate_authors
from app.models import Paper


def _paper_card(paper: Paper, summary: str | None) -> str:
    title = html.escape(paper.title or "Untitled")
    link = f'<a href="{html.escape(paper.url)}">{title}</a>' if paper.url else title

    meta = " · ".join(
        p
        for p in [
            html.escape(_truncate_authors(paper.authors)),
            html.escape(paper.journal) if paper.journal else None,
            paper.source.upper(),
            paper.published_date,
        ]
        if p
    )

    evidence = _evidence_line(paper)
    evidence_html = f'<div class="groupCoauthor">{html.escape(evidence)}</div>' if evidence else ""

    body = summary or paper.abstract or ""
    if not summary and len(body) > 220:
        body = body[:220].rstrip() + "…"
    body_html = f'<div class="rowMeta" style="padding:12px 16px 14px">{html.escape(body)}</div>' if body else ""

    return (
        '<div class="group">'
        '<div class="groupHeader"><div class="groupHeaderTop">'
        f'<span class="groupTitle">{link}</span>'
        f'<span class="groupCount">score {paper.score:.0f}</span>'
        "</div>"
        f'<div class="groupMeta">{html.escape(meta)}</div>'
        f"{evidence_html}"
        "</div>"
        f"{body_html}"
        "</div>"
    )


def _topic_section(topic_name: str, papers: list[Paper], summaries: dict[str, str]) -> str:
    count = len(papers)
    heading = (
        f'<h2 class="monthHeading">{html.escape(topic_name)} '
        f'<span class="monthCount">{count} paper{"s" if count != 1 else ""}</span></h2>'
    )
    if not papers:
        return f'{heading}<p class="empty">No new papers found.</p>'
    cards = "\n".join(_paper_card(p, summaries.get(p.source_id)) for p in papers)
    return f'{heading}<div class="monthBody">{cards}</div>'


def build_digest_page(
    topic_results: list[tuple[str, list[Paper]]],
    summaries: dict[str, str] | None = None,
) -> str:
    """Render the full static HTML digest page from one run's topic_results."""
    summaries = summaries or {}
    total = sum(len(papers) for _, papers in topic_results)

    if total:
        body = "\n".join(
            f'<section class="month">{_topic_section(name, papers, summaries)}</section>'
            for name, papers in topic_results
        )
        subtitle = f"{total} new paper{'s' if total != 1 else ''} this week, grouped by topic."
    else:
        body = '<p class="empty">No new papers this week — check back next Monday.</p>'
        subtitle = "Nothing new this week."

    updated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Paper Watch Digest</title>
<style>
{_STYLE}
</style>
</head>
<body>
<header class="topbar">
  <div class="logo">ourak<span>.</span></div>
  <div class="topbarRight">Paper Watch Digest &middot; Last fetched {updated}</div>
</header>
<main class="content">
  <h1>Paper Watch Digest</h1>
  <p class="subtitle">{subtitle}</p>
  {body}
</main>
</body>
</html>"""
