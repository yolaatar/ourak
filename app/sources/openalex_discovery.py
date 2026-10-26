"""OpenAlex-based discovery source for the main paper-watch pipeline.

Distinct from app/sources/openalex.py, which is lab_watch's citation tracker —
kept separate so that working, battle-tested pipeline is never touched here.
Reuses its helpers (_abstract_from_index, _get_all, _short_id, _chunks,
fetch_citing_papers) rather than re-deriving them.

Two relevance signals that pure keyword matching (the other sources) can't
provide:
  - OpenAlex's own ML-derived concept tags on each paper (fetch_openalex)
  - "this paper cites something you already cite" (fetch_cites_known_work),
    independent of keyword overlap entirely
"""

import logging
from datetime import datetime, timedelta, timezone

import requests

from app.models import LabPaper, Paper, Topic
from app.sources.openalex import (
    _REPORT_TYPES,
    _WORKS_URL,
    _abstract_from_index,
    _base_params,
    _chunks,
    _get_all,
    _short_id,
    fetch_citing_papers,
)

logger = logging.getLogger(__name__)

_OR_CHUNK = 50
_MAX_QUERY_TERMS = 50  # chunked by _OR_CHUNK; one filter call covers most topics
_CONCEPT_MIN_SCORE = 0.4  # OpenAlex concept scores are 0-1; drop weak tags
_SELECT_FIELDS = (
    "id,doi,title,abstract_inverted_index,authorships,publication_date,"
    "primary_location,cited_by_count,concepts"
)


def _since(days_back: int) -> str:
    return (datetime.now(timezone.utc).date() - timedelta(days=days_back)).isoformat()


def _build_filters(topic: Topic, days_back: int | None) -> list[str]:
    """One filter string per OR-chunk of include_any terms, AND'd with
    include_all terms, the report-type filter, and the date window.

    Mirrors app/sources/openalex.py::_lab_filters' chunking so no single
    filter value exceeds OpenAlex's practical length.
    """
    terms = (topic.include_any or topic.include_all)[:_MAX_QUERY_TERMS]
    if not terms:
        return []

    since = _since(days_back) if days_back is not None else None
    filters: list[str] = []
    for chunk in _chunks(terms, _OR_CHUNK):
        parts = [f"title_and_abstract.search:{'|'.join(chunk)}"]
        parts += [f"title_and_abstract.search:{term}" for term in topic.include_all]
        parts.append(_REPORT_TYPES)
        if since:
            parts.append(f"from_publication_date:{since}")
        filters.append(",".join(parts))
    return filters


def _parse_work(work: dict, topic_name: str) -> Paper:
    work_id = _short_id(work.get("id"))
    doi_url = work.get("doi")
    doi = doi_url.removeprefix("https://doi.org/") if doi_url else None
    location = work.get("primary_location") or {}
    source = location.get("source") or {}
    authors = [
        (a.get("author") or {}).get("display_name", "")
        for a in work.get("authorships") or []
    ]
    concepts = [
        c["display_name"]
        for c in (work.get("concepts") or [])
        if (c.get("score") or 0) >= _CONCEPT_MIN_SCORE
    ]
    return Paper(
        source="openalex",
        source_id=f"openalex:{work_id}",
        title=work.get("title") or "",
        abstract=_abstract_from_index(work.get("abstract_inverted_index")),
        authors=[a for a in authors if a],
        published_date=work.get("publication_date"),
        journal=source.get("display_name"),
        doi=doi,
        url=doi_url or location.get("landing_page_url") or work.get("id"),
        topics_matched=[topic_name],
        cited_by_count=work.get("cited_by_count") or 0,
        concepts=concepts,
    )


def fetch_openalex(topic: Topic, days_back: int, max_results: int) -> list[Paper]:
    """Fetch papers from OpenAlex for a topic.

    Carries OpenAlex's own concept tags and citation count — a relevance
    signal independent of literal keyword overlap (see app/scoring.py).
    Returns an empty list on any network or parse error (house style, matches
    the other source fetchers).
    """
    try:
        filters = _build_filters(topic, days_back)
        if not filters:
            logger.warning("No query terms for topic %s — skipping OpenAlex", topic.name)
            return []

        papers: list[Paper] = []
        for f in filters:
            # A single page, capped at max_results — NOT _get_all, which pages
            # through every match with no limit. A broad topic's filter can
            # match tens of thousands of works (seen: 28k+ for a 55-term OR),
            # so exhaustive pagination here would hang the whole fetch.
            #
            # Deliberately no explicit `sort` — OpenAlex's default is
            # relevance-ranked, which matters enormously once the match count
            # is in the thousands: sorting by publication_date instead surfaces
            # whatever is newest anywhere in OpenAlex that happens to contain
            # any one of the OR terms (verified live: unrelated physics
            # preprints and battery-electrode papers ranked above EM/axon
            # segmentation work). from_publication_date in the filter already
            # bounds the time window; relevance ranking picks the best within it.
            params = {
                **_base_params(),
                "filter": f,
                "select": _SELECT_FIELDS,
                "per_page": min(max_results, 200),
            }
            resp = requests.get(_WORKS_URL, params=params, timeout=30)
            resp.raise_for_status()
            works = resp.json().get("results", [])
            papers.extend(_parse_work(w, topic.name) for w in works)
            if len(papers) >= max_results:
                break
        return papers[:max_results]

    except Exception as exc:
        logger.warning("OpenAlex fetch failed for topic %s: %s", topic.name, exc)
        return []


def resolve_seed_concepts(seed_works: list[str]) -> set[str]:
    """Return the union of OpenAlex concept tags on a topic's seed_works.

    Used as the topic's own concept set for scoring (app/scoring.py's
    topic_concepts) — a candidate paper sharing concepts with the papers this
    research already builds on is relevant independent of keyword overlap.

    Returns an empty set on any network or parse error (house style).
    """
    if not seed_works:
        return set()

    try:
        ids = [w for w in seed_works if w.startswith("W") and w[1:].isdigit()]
        dois = [w.removeprefix("https://doi.org/") for w in seed_works if w not in ids]

        concepts: set[str] = set()
        for key, values in (("ids.openalex", ids), ("doi", dois)):
            for chunk in _chunks(values, _OR_CHUNK):
                if not chunk:
                    continue
                for w in _get_all(f"{key}:{'|'.join(chunk)}", "id,concepts"):
                    concepts.update(
                        c["display_name"]
                        for c in (w.get("concepts") or [])
                        if (c.get("score") or 0) >= _CONCEPT_MIN_SCORE
                    )
        return concepts

    except Exception as exc:
        logger.warning("resolve_seed_concepts failed for seed_works %s: %s", seed_works, exc)
        return set()


def fetch_cites_known_work(seed_works: list[str], days_back: int) -> list[LabPaper]:
    """Papers citing any of a topic's seed_works — papers the user's own
    research builds on (e.g. AxonDeepSeg, SCT). A relevance signal that
    doesn't depend on keyword overlap at all.

    Thin wrapper around openalex.py's already-working fetch_citing_papers.
    seed_works: OpenAlex work IDs ("W123...") or DOIs/DOI URLs.

    Returns an empty list on any network or parse error (house style).
    """
    if not seed_works:
        return []

    try:
        ids = [w for w in seed_works if w.startswith("W") and w[1:].isdigit()]
        dois = [
            w.removeprefix("https://doi.org/")
            for w in seed_works
            if w not in ids
        ]

        seed_work_lookup: dict[str, dict] = {}
        if ids:
            for chunk in _chunks(ids, _OR_CHUNK):
                for w in _get_all(f"ids.openalex:{'|'.join(chunk)}", "id,title"):
                    seed_work_lookup[_short_id(w["id"])] = {"title": w.get("title") or ""}
        if dois:
            for chunk in _chunks(dois, _OR_CHUNK):
                for w in _get_all(f"doi:{'|'.join(chunk)}", "id,title"):
                    seed_work_lookup[_short_id(w["id"])] = {"title": w.get("title") or ""}

        if not seed_work_lookup:
            logger.warning("No seed_works resolved on OpenAlex: %s", seed_works)
            return []

        return fetch_citing_papers(seed_work_lookup, days_back)

    except Exception as exc:
        logger.warning("fetch_cites_known_work failed for seed_works %s: %s", seed_works, exc)
        return []
