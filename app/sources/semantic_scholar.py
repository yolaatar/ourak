"""Semantic Scholar source fetcher using the Graph API."""

import logging
import os
import time
from datetime import datetime, timedelta

import requests

from app.models import Paper, Topic

logger = logging.getLogger(__name__)

_S2_SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
_FIELDS = "paperId,externalIds,title,abstract,authors,year,publicationDate,venue,journal,openAccessPdf"
_SLEEP_UNAUTH = 1.0   # ~1 req/s without key
_SLEEP_AUTH = 0.1     # 10 req/s with key


def _get_api_key() -> str | None:
    return os.getenv("S2_API_KEY") or None


def _build_query(topic: Topic) -> str:
    """Build a Semantic Scholar keyword query from a Topic.

    S2 free-text search doesn't support boolean operators in the same way,
    so we join include_any terms with | (OR) and append include_all terms with +.
    """
    parts: list[str] = []
    if topic.include_any:
        parts.append(" | ".join(f'"{t}"' for t in topic.include_any))
    if topic.include_all:
        parts.extend(f'+"{t}"' for t in topic.include_all)
    return " ".join(parts)


def _iso_date(days_back: int) -> str:
    """Return the ISO date string for the start of the window."""
    from datetime import timezone
    return (datetime.now(timezone.utc).date() - timedelta(days=days_back)).isoformat()


def _parse_results(data: dict, topic_name: str, cutoff_date: str | None) -> list[Paper]:
    """Convert S2 API result dicts into Paper objects."""
    papers: list[Paper] = []

    for item in data.get("data", []):
        try:
            paper_id = item.get("paperId", "")

            title = item.get("title") or ""

            abstract = item.get("abstract") or None

            authors = [a.get("name", "") for a in item.get("authors", []) if a.get("name")]

            # Prefer publicationDate (YYYY-MM-DD), fall back to year
            pub_date: str | None = item.get("publicationDate") or None
            if not pub_date and item.get("year"):
                pub_date = str(item["year"])

            # Filter out papers outside the date window (skip if no cutoff)
            if cutoff_date and pub_date and len(pub_date) >= 10:
                if pub_date[:10] < cutoff_date:
                    continue

            # Venue / journal
            venue = item.get("venue") or None
            if not venue:
                journal_info = item.get("journal") or {}
                venue = journal_info.get("name") or None

            # DOI
            ext_ids = item.get("externalIds") or {}
            doi = ext_ids.get("DOI") or None

            # URL: prefer open-access PDF, fall back to S2 page
            pdf_info = item.get("openAccessPdf") or {}
            url = pdf_info.get("url") or (
                f"https://www.semanticscholar.org/paper/{paper_id}" if paper_id else None
            )

            papers.append(
                Paper(
                    source="semantic_scholar",
                    source_id=f"s2:{paper_id}",
                    title=title,
                    abstract=abstract,
                    authors=authors,
                    published_date=pub_date,
                    journal=venue,
                    doi=doi,
                    url=url,
                    topics_matched=[topic_name],
                )
            )
        except Exception as exc:
            logger.warning("Failed to parse S2 paper: %s", exc)

    return papers


def fetch_semantic_scholar(topic: Topic, days_back: int, max_results: int) -> list[Paper]:
    """Fetch papers from Semantic Scholar for a given topic.

    Returns an empty list on any network or parse error.
    """
    try:
        api_key = _get_api_key()
        sleep_s = _SLEEP_AUTH if api_key else _SLEEP_UNAUTH

        query = _build_query(topic)
        if not query:
            logger.warning("No query terms for topic %s — skipping Semantic Scholar", topic.name)
            return []

        cutoff = _iso_date(days_back) if days_back is not None else None

        headers: dict[str, str] = {}
        if api_key:
            headers["x-api-key"] = api_key

        # S2 paginates at 100 results max; fetch in one shot up to max_results (≤100)
        limit = min(max_results, 100)
        params: dict = {
            "query": query,
            "fields": _FIELDS,
            "limit": limit,
        }
        if cutoff:
            params["publicationDateOrYear"] = f"{cutoff}:"
        # When no cutoff, S2 returns results ranked by relevance

        logger.info("S2 search: topic=%s query=%r", topic.name, query)
        resp = requests.get(_S2_SEARCH_URL, params=params, headers=headers, timeout=30)

        if resp.status_code == 400:
            # S2 returns 400 for some complex queries; log and bail gracefully
            logger.warning("S2 returned 400 for topic %s — query may be unsupported", topic.name)
            return []

        resp.raise_for_status()
        time.sleep(sleep_s)

        return _parse_results(resp.json(), topic.name, cutoff)

    except Exception as exc:
        logger.warning("Semantic Scholar fetch failed for topic %s: %s", topic.name, exc)
        return []
