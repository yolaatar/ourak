"""Relevance scoring for research papers.

Scores are normalized to 0–100. Recency acts as a multiplier (up to +30%)
so a recent paper gets a boost but can't outrank a much more relevant one.
"""

import math
from datetime import datetime, date, timezone

from app.models import Paper, Topic

_CITATION_AGE_FLOOR_DAYS = 90  # below this, skip the citation-count boost — a
# brand-new preprint hasn't had time to accumulate citations yet, so scoring
# it on a count of ~0 would unfairly bury it next to older work


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _recency_multiplier(published_date: str | None) -> float:
    """Return a multiplier based on how recently the paper was published.

    Returns 1.0–1.3 so recency can boost a score by up to 30%.
    """
    if not published_date:
        return 1.0
    try:
        pub = datetime.strptime(published_date[:10], "%Y-%m-%d").date()
    except ValueError:
        return 1.0
    delta = (_today() - pub).days
    if delta <= 7:
        return 1.3
    if delta <= 14:
        return 1.2
    if delta <= 30:
        return 1.1
    return 1.0


def _is_established(published_date: str | None) -> bool:
    """True once a paper has had enough time to plausibly accumulate citations."""
    if not published_date:
        return False
    try:
        pub = datetime.strptime(published_date[:10], "%Y-%m-%d").date()
    except ValueError:
        return False
    return (_today() - pub).days > _CITATION_AGE_FLOOR_DAYS


def compute_term_boosts(upvoted: list, flagged: list, topic: Topic) -> dict[str, float]:
    """Derive per-term score adjustments from user feedback.

    Upvoted paper → matching terms get +2 each occurrence.
    Flagged paper  → matching terms get -3 each occurrence.
    Returns only terms with a non-zero net adjustment.
    """
    boosts: dict[str, float] = {}
    for paper in upvoted:
        combined = f"{paper.title} {(paper.abstract or '')}".lower()
        for term in topic.include_any:
            if term.lower() in combined:
                boosts[term] = boosts.get(term, 0.0) + 2.0
    for paper in flagged:
        combined = f"{paper.title} {(paper.abstract or '')}".lower()
        for term in topic.include_any:
            if term.lower() in combined:
                boosts[term] = boosts.get(term, 0.0) - 3.0
    return {k: v for k, v in boosts.items() if v != 0.0}


def score_paper(
    paper: Paper,
    topic: Topic,
    *,
    use_recency: bool = True,
    term_boosts: dict[str, float] | None = None,
    topic_concepts: set[str] | None = None,
    cites_known_work: bool = False,
) -> float:
    """Score a single paper against a topic's keyword lists, plus optional
    OpenAlex-derived signals that don't depend on literal keyword overlap.

    Relevance score (0–100):
      Keyword matching builds a raw score, then normalized via sigmoid-like
      mapping so that diminishing returns kick in naturally.

      Raw score components:
        +4 per include_any term matched in title+abstract
        +6 per include_all term matched
        -5 per exclude term matched
        +3 bonus if any include_any matched in title
        +2 bonus if any include_any matched in abstract
        +2 per boost_author matched
        +2 per boost_venue matched
        +5 per OpenAlex concept shared with topic_concepts, capped at +20
        +15 flat if cites_known_work (cites a paper this research builds on)
        up to +10, log-scaled on cited_by_count (skipped if <90 days old)

      Then: normalized = 100 * raw / (raw + K)  where K=20
      Finally: score = normalized * recency_multiplier (capped at 100)
    """
    title_lower = paper.title.lower()
    abstract_lower = (paper.abstract or "").lower()
    combined = f"{title_lower} {abstract_lower}"

    raw = 0.0

    # include_any scoring
    any_in_title = False
    any_in_abstract = False
    for term in topic.include_any:
        t = term.lower()
        if t in combined:
            boost = term_boosts.get(term, 0.0) if term_boosts else 0.0
            raw += 4.0 + boost
        if t in title_lower:
            any_in_title = True
        if t in abstract_lower:
            any_in_abstract = True

    if any_in_title:
        raw += 3.0
    if any_in_abstract:
        raw += 2.0

    # include_all scoring
    for term in topic.include_all:
        if term.lower() in combined:
            raw += 6.0

    # exclude penalty
    for term in topic.exclude:
        if term.lower() in combined:
            raw -= 5.0

    # author boost
    author_text = " ".join(paper.authors).lower()
    for author in topic.boost_authors:
        if author.lower() in author_text:
            raw += 2.0

    # venue boost
    venue_text = (paper.journal or "").lower()
    for venue in topic.boost_venues:
        if venue.lower() in venue_text:
            raw += 2.0

    # OpenAlex concept overlap — catches real relevance that different
    # wording in the abstract would make a literal keyword search miss
    if topic_concepts and paper.concepts:
        overlap = len(topic_concepts & set(paper.concepts))
        if overlap:
            raw += min(5.0 * overlap, 20.0)

    # Cites a paper this research builds on (topic.seed_works) — relevant
    # regardless of whether it shares any vocabulary with the keyword lists
    if cites_known_work:
        raw += 15.0

    # Citation count — light boost only once a paper has had time to
    # accumulate citations, so new preprints aren't penalized for having none
    if paper.cited_by_count and _is_established(paper.published_date):
        raw += min(math.log10(paper.cited_by_count + 1) * 4.0, 10.0)

    # Floor at 0
    if raw <= 0:
        return 0.0

    # Normalize to 0–100 with diminishing returns (K=20)
    # raw=5 → 20, raw=10 → 33, raw=20 → 50, raw=40 → 67, raw=80 → 80
    K = 20.0
    normalized = 100.0 * raw / (raw + K)

    # Apply recency as multiplier
    if use_recency:
        normalized *= _recency_multiplier(paper.published_date)

    return round(min(normalized, 100.0), 1)


def score_papers(
    papers: list[Paper],
    topic: Topic,
    *,
    use_recency: bool = True,
    term_boosts: dict[str, float] | None = None,
    topic_concepts: set[str] | None = None,
    cites_known_work_ids: set[str] | None = None,
) -> list[Paper]:
    """Score all papers in-place and return the list.

    topic_concepts and cites_known_work_ids are resolved once per topic per
    run by the caller (network calls — see app/sources/openalex_discovery.py)
    and passed in here so scoring itself stays pure and fast.

    Every paper gets an evidence_tier: "keyword_only" by default, so the
    digest always has something to show, upgraded to "mentioned"/"confirmed"
    later by the full-text verification pass (app/fulltext.py) for papers
    whose score lands in the borderline band.
    """
    cites_known_work_ids = cites_known_work_ids or set()
    for paper in papers:
        paper.score = score_paper(
            paper,
            topic,
            use_recency=use_recency,
            term_boosts=term_boosts,
            topic_concepts=topic_concepts,
            cites_known_work=paper.source_id in cites_known_work_ids,
        )
        if paper.evidence_tier is None:
            paper.evidence_tier = "keyword_only"
    return papers
