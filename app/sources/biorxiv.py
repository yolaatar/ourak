"""bioRxiv and medRxiv source fetcher using the REST API.

Since the bioRxiv API does not support keyword search, we fetch recent papers
by date range and filter client-side against the topic's keyword lists.
"""

import logging
import time
from datetime import datetime, timedelta, timezone

import requests

from app.models import Paper, Topic

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.biorxiv.org/details"
_SERVERS = ["biorxiv", "medrxiv"]
_SLEEP = 1.0
_PAGE_SIZE = 100  # API maximum
_MAX_PAGES = 1    # bioRxiv API is slow (~10s/page) and has no keyword search


def _build_date_interval(days_back: int) -> str:
    """Return a 'YYYY-MM-DD/YYYY-MM-DD' interval string."""
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=days_back)
    return f"{start.isoformat()}/{today.isoformat()}"


def _matches_topic(item: dict, topic: Topic) -> bool:
    """Check if a paper dict matches the topic's keyword filters."""
    title = (item.get("title") or "").lower()
    abstract = (item.get("abstract") or "").lower()
    combined = f"{title} {abstract}"

    # Check exclude first — fast rejection
    for term in topic.exclude:
        if term.lower() in combined:
            return False

    # Check include_all — all must be present
    for term in topic.include_all:
        if term.lower() not in combined:
            return False

    # Check include_any — at least one must match
    if topic.include_any:
        if not any(term.lower() in combined for term in topic.include_any):
            return False

    return True


def _parse_authors(authors_str: str) -> list[str]:
    """Parse 'Last, F.; Last2, F2.' into ['Last F', 'Last2 F2']."""
    if not authors_str:
        return []
    authors = []
    for part in authors_str.split(";"):
        name = part.strip().rstrip(".")
        if "," in name:
            last, first = name.split(",", 1)
            authors.append(f"{last.strip()} {first.strip()}")
        elif name:
            authors.append(name)
    return authors


def _parse_results(data: dict, server: str, topic: Topic) -> list[Paper]:
    """Convert API response into a list of topic-filtered Paper objects."""
    papers: list[Paper] = []
    for item in data.get("collection", []):
        try:
            if not _matches_topic(item, topic):
                continue

            doi = item.get("doi", "")
            papers.append(
                Paper(
                    source=server,
                    source_id=f"{server}:{doi}",
                    title=item.get("title", ""),
                    abstract=item.get("abstract"),
                    authors=_parse_authors(item.get("authors", "")),
                    published_date=item.get("date"),
                    journal=item.get("category"),
                    doi=doi,
                    url=f"https://doi.org/{doi}" if doi else None,
                    topics_matched=[topic.name],
                )
            )
        except Exception as exc:
            logger.warning("Failed to parse bioRxiv item: %s", exc)
    return papers


def _fetch_server(server: str, topic: Topic, days_back: int, max_results: int) -> list[Paper]:
    """Fetch from a single server (biorxiv or medrxiv).

    Caps at _MAX_PAGES pages to avoid spending minutes downloading
    thousands of papers that mostly get filtered out.
    """
    interval = _build_date_interval(days_back)
    papers: list[Paper] = []
    cursor = 0
    page = 0

    while len(papers) < max_results and page < _MAX_PAGES:
        url = f"{_BASE_URL}/{server}/{interval}/{cursor}"
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        batch = _parse_results(data, server, topic)
        papers.extend(batch)

        # Check if there are more pages
        messages = data.get("messages", [{}])
        total = int(messages[0].get("total", 0)) if messages else 0
        cursor += _PAGE_SIZE
        page += 1
        if cursor >= total:
            break

        time.sleep(_SLEEP)

    return papers[:max_results]


def fetch_biorxiv(topic: Topic, days_back: int, max_results: int) -> list[Paper]:
    """Fetch papers from bioRxiv and medRxiv for a given topic.

    Runs both servers in parallel. Returns an empty list on error.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    if days_back is None:
        logger.debug("bioRxiv skipped — no keyword search for relevance mode")
        return []

    all_papers: list[Paper] = []

    with ThreadPoolExecutor(max_workers=len(_SERVERS)) as pool:
        futures = {
            pool.submit(_fetch_server, server, topic, days_back, max_results): server
            for server in _SERVERS
        }
        for future in as_completed(futures):
            server = futures[future]
            try:
                all_papers.extend(future.result())
            except Exception as exc:
                logger.warning("%s fetch failed for topic %s: %s", server, topic.name, exc)

    return all_papers
