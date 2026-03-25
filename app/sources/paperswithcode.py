"""Papers With Code source fetcher."""

import logging
import time
from datetime import datetime, timedelta, timezone

import requests

from app.models import Paper, Topic

logger = logging.getLogger(__name__)

_PWC_API = "https://paperswithcode.com/api/v1/papers/"
_SLEEP = 1.0


def _build_query(topic: Topic) -> str:
    """Build a search query string from topic keywords (max 5 terms)."""
    # Prefer include_all (most specific), then include_any
    terms = list(topic.include_all) + list(topic.include_any)
    # PWC search chokes on very long queries — keep the top 5 terms
    terms = terms[:5]
    return " ".join(terms) if terms else ""


def _cutoff_date(days_back: int | None) -> str | None:
    """Return ISO date string for the start of the search window."""
    if days_back is None:
        return None
    return (datetime.now(timezone.utc).date() - timedelta(days=days_back)).isoformat()


def _parse_results(data: dict, topic_name: str, cutoff_date: str | None) -> list[Paper]:
    """Convert API response into Paper objects, optionally filtering by date."""
    papers: list[Paper] = []
    for item in data.get("results", []):
        try:
            pub_date = item.get("published") or None
            if cutoff_date and pub_date and pub_date < cutoff_date:
                continue

            paper_id = item.get("id", "")
            authors = item.get("authors") or []

            # Prefer GitHub URL if a repo exists, else url_abs
            repos = item.get("repositories") or []
            github_url = repos[0]["url"] if repos else None
            url = github_url or item.get("url_abs") or None

            papers.append(
                Paper(
                    source="paperswithcode",
                    source_id=f"pwc:{paper_id}",
                    title=item.get("title", ""),
                    abstract=item.get("abstract"),
                    authors=authors,
                    published_date=pub_date,
                    journal=item.get("proceeding"),
                    doi=None,
                    url=url,
                    topics_matched=[topic_name],
                )
            )
        except Exception as exc:
            logger.warning("Failed to parse PWC paper: %s", exc)
    return papers


def fetch_paperswithcode(topic: Topic, days_back: int, max_results: int) -> list[Paper]:
    """Fetch papers from Papers With Code for a given topic.

    Returns an empty list on any network or parse error.
    Probes the API first and skips if it returns HTML instead of JSON.
    """
    try:
        probe = requests.head(_PWC_API, timeout=5)
        if "json" not in probe.headers.get("content-type", ""):
            logger.debug("PWC API returned HTML — skipping")
            return []

        query = _build_query(topic)
        if not query:
            logger.warning("No query terms for topic %s — skipping PWC", topic.name)
            return []

        cutoff = _cutoff_date(days_back)
        params = {
            "q": query,
            "items_per_page": min(max_results, 50),
            "page": 1,
        }

        logger.info("PWC search: topic=%s query=%r", topic.name, query)
        resp = requests.get(_PWC_API, params=params, timeout=30)
        resp.raise_for_status()
        time.sleep(_SLEEP)

        # Guard against non-JSON responses (HTML error pages, empty body)
        content_type = resp.headers.get("content-type", "")
        if "json" not in content_type:
            logger.warning("PWC returned non-JSON content-type: %s", content_type)
            return []

        return _parse_results(resp.json(), topic.name, cutoff)

    except Exception as exc:
        logger.warning("PWC fetch failed for topic %s: %s", topic.name, exc)
        return []
