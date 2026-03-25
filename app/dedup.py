"""Cross-source deduplication for research papers.

Strategy (two passes):
  1. Exact DOI match  — most reliable; handles arXiv ↔ S2 overlaps.
  2. Fuzzy title match — catches papers without a DOI using rapidfuzz ratio ≥ 92.

When duplicates are merged the richer record wins field-by-field, and all
source_ids are preserved in `alt_ids` so seen-ID tracking stays complete.
"""

import logging
import re

from rapidfuzz import fuzz

from app.models import Paper

logger = logging.getLogger(__name__)

# Source priority for choosing the "primary" record when merging.
# Lower index = higher priority.
_SOURCE_PRIORITY = ["semantic_scholar", "arxiv", "biorxiv"]
_TITLE_SIMILARITY_THRESHOLD = 92  # percent


def _norm_doi(doi: str) -> str:
    """Normalize a DOI to lowercase with no surrounding whitespace."""
    return doi.strip().lower()


def _norm_title(title: str) -> str:
    """Strip punctuation and fold case for fuzzy comparison."""
    return re.sub(r"[^\w\s]", "", title).lower()


def _source_rank(paper: Paper) -> int:
    try:
        return _SOURCE_PRIORITY.index(paper.source)
    except ValueError:
        return len(_SOURCE_PRIORITY)


def _merge(primary: Paper, duplicate: Paper) -> Paper:
    """Return a new Paper combining the best fields of two records."""
    # Choose the higher-priority source as the base
    if _source_rank(duplicate) < _source_rank(primary):
        primary, duplicate = duplicate, primary

    def pick(a, b):
        """Return a if it is a non-empty/non-None value, else b."""
        if a is None or a == "" or a == []:
            return b
        return a

    merged_alt_ids = list({
        *primary.alt_ids,
        *duplicate.alt_ids,
        duplicate.source_id,
    } - {primary.source_id})

    # Prefer longer abstract (more complete)
    abstract = primary.abstract
    if duplicate.abstract and (not abstract or len(duplicate.abstract) > len(abstract)):
        abstract = duplicate.abstract

    # Prefer longer author list
    authors = primary.authors if len(primary.authors) >= len(duplicate.authors) else duplicate.authors

    # Prefer more specific date (YYYY-MM-DD > YYYY)
    pub_date = primary.published_date
    dup_date = duplicate.published_date
    if dup_date and (not pub_date or (len(dup_date) > len(pub_date))):
        pub_date = dup_date

    return primary.model_copy(update={
        "abstract": abstract,
        "authors": authors,
        "published_date": pub_date,
        "journal": pick(primary.journal, duplicate.journal),
        "doi": pick(primary.doi, duplicate.doi),
        "url": pick(primary.url, duplicate.url),
        "topics_matched": list(set(primary.topics_matched) | set(duplicate.topics_matched)),
        "alt_ids": merged_alt_ids,
        "score": 0.0,  # will be rescored after dedup
    })


def dedup_papers(papers: list[Paper]) -> list[Paper]:
    """Deduplicate a list of papers fetched from multiple sources.

    Returns a new list with duplicates merged, preserving all source IDs.
    """
    # --- Pass 1: DOI-based grouping ---
    doi_groups: dict[str, int] = {}   # normalised DOI → index in `result`
    result: list[Paper] = []
    no_doi: list[Paper] = []

    for paper in papers:
        if paper.doi:
            key = _norm_doi(paper.doi)
            if key in doi_groups:
                idx = doi_groups[key]
                result[idx] = _merge(result[idx], paper)
                logger.debug("DOI dedup: merged %s into %s", paper.source_id, result[idx].source_id)
            else:
                doi_groups[key] = len(result)
                result.append(paper)
        else:
            no_doi.append(paper)

    # --- Pass 2: fuzzy title matching for papers without a DOI ---
    # Build a lookup of normalised titles already in `result`
    result_titles: list[str] = [_norm_title(p.title) for p in result]

    for paper in no_doi:
        norm = _norm_title(paper.title)
        best_score = 0.0
        best_idx = -1

        for i, existing_title in enumerate(result_titles):
            score = fuzz.ratio(norm, existing_title)
            if score > best_score:
                best_score = score
                best_idx = i

        if best_score >= _TITLE_SIMILARITY_THRESHOLD:
            result[best_idx] = _merge(result[best_idx], paper)
            result_titles[best_idx] = _norm_title(result[best_idx].title)
            logger.debug(
                "Title dedup (%.0f%%): merged %s into %s",
                best_score, paper.source_id, result[best_idx].source_id,
            )
        else:
            result_titles.append(norm)
            result.append(paper)

    original = len(papers)
    deduped = len(result)
    if original != deduped:
        logger.info("Dedup: %d → %d papers (%d duplicates removed)", original, deduped, original - deduped)

    return result
