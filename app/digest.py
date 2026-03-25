"""Digest builder — converts scored paper lists into a markdown report."""

from datetime import datetime, timezone

from app.models import Paper


def _truncate_authors(authors: list[str], max_n: int = 3) -> str:
    """Return author string truncated to max_n names."""
    if not authors:
        return "Unknown authors"
    shown = authors[:max_n]
    suffix = " et al." if len(authors) > max_n else ""
    return ", ".join(shown) + suffix


def _abstract_snippet(abstract: str | None, chars: int = 200) -> str:
    """Return the first `chars` characters of an abstract."""
    if not abstract:
        return "_No abstract available._"
    snippet = abstract[:chars].rstrip()
    if len(abstract) > chars:
        snippet += "…"
    return snippet


def build_digest(
    topic_results: list[tuple[str, list[Paper]]],
    summaries: dict[str, str] | None = None,
) -> str:
    """Build a markdown digest from a list of (topic_name, papers) tuples.

    If `summaries` is provided (source_id -> sentence), it is shown instead of
    the raw abstract snippet.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    total = sum(len(papers) for _, papers in topic_results)

    lines: list[str] = [
        f"# Paper-Watch Digest",
        f"",
        f"**Run date:** {now}  ",
        f"**Total papers:** {total}",
        f"",
    ]

    for topic_name, papers in topic_results:
        lines.append(f"## {topic_name}")
        lines.append("")

        if not papers:
            lines.append("_No new papers found._")
            lines.append("")
            continue

        for paper in papers:
            title_md = f"[{paper.title}]({paper.url})" if paper.url else paper.title
            lines.append(f"### {title_md}")
            lines.append("")
            lines.append(f"**Authors:** {_truncate_authors(paper.authors)}  ")

            meta_parts: list[str] = []
            if paper.journal:
                meta_parts.append(paper.journal)
            meta_parts.append(paper.source.upper())
            if paper.published_date:
                meta_parts.append(paper.published_date)
            lines.append(f"**Source:** {' | '.join(meta_parts)}  ")
            lines.append(f"**Score:** {paper.score:.1f}  ")
            lines.append("")
            if summaries and paper.source_id in summaries:
                lines.append(f"**Summary:** {summaries[paper.source_id]}")
            else:
                lines.append(_abstract_snippet(paper.abstract))
            lines.append("")
            lines.append("---")
            lines.append("")

    return "\n".join(lines)
