"""Relevance scoring for research papers."""

from datetime import datetime, date, timezone

from app.models import Paper, Topic


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _recency_bonus(published_date: str | None) -> float:
    """Return a bonus based on how recently the paper was published."""
    if not published_date:
        return 0.0
    try:
        pub = datetime.strptime(published_date[:10], "%Y-%m-%d").date()
    except ValueError:
        return 0.0
    delta = (_today() - pub).days
    if delta <= 7:
        return 4.0
    if delta <= 14:
        return 3.0
    if delta <= 30:
        return 2.0
    return 0.0


def score_paper(paper: Paper, topic: Topic, *, use_recency: bool = True) -> float:
    """Score a single paper against a topic's keyword lists.

    Formula:
      +4 per include_any term matched in title+abstract
      +6 per include_all term matched
      -5 per exclude term matched
      +3 if any include_any term matched in title
      +2 if any include_any term matched in abstract
      + recency_bonus (if use_recency=True)
      +2 per boost_author matched
      +2 per boost_venue matched
    """
    title_lower = paper.title.lower()
    abstract_lower = (paper.abstract or "").lower()
    combined = f"{title_lower} {abstract_lower}"

    score = 0.0

    # include_any scoring
    any_in_title = False
    any_in_abstract = False
    for term in topic.include_any:
        t = term.lower()
        if t in combined:
            score += 4.0
        if t in title_lower:
            any_in_title = True
        if t in abstract_lower:
            any_in_abstract = True

    if any_in_title:
        score += 3.0
    if any_in_abstract:
        score += 2.0

    # include_all scoring
    for term in topic.include_all:
        if term.lower() in combined:
            score += 6.0

    # exclude penalty
    for term in topic.exclude:
        if term.lower() in combined:
            score -= 5.0

    # recency
    if use_recency:
        score += _recency_bonus(paper.published_date)

    # author boost
    author_text = " ".join(paper.authors).lower()
    for author in topic.boost_authors:
        if author.lower() in author_text:
            score += 2.0

    # venue boost
    venue_text = (paper.journal or "").lower()
    for venue in topic.boost_venues:
        if venue.lower() in venue_text:
            score += 2.0

    return score


def score_papers(papers: list[Paper], topic: Topic, *, use_recency: bool = True) -> list[Paper]:
    """Score all papers in-place and return the list."""
    for paper in papers:
        paper.score = score_paper(paper, topic, use_recency=use_recency)
    return papers
