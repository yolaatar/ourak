"""arXiv source fetcher using the arXiv Atom API."""

import logging
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

import requests

from app.models import Paper, Topic

logger = logging.getLogger(__name__)

_ARXIV_API = "https://export.arxiv.org/api/query"
_ATOM_NS = "http://www.w3.org/2005/Atom"
_ARXIV_NS = "http://arxiv.org/schemas/atom"
_SLEEP = 3.0  # arXiv asks for ≥3s between requests


def _build_query(topic: Topic) -> str:
    """Construct an arXiv search query from a Topic."""
    parts: list[str] = []
    if topic.include_any:
        any_clause = " OR ".join(
            f'(ti:"{t}" OR abs:"{t}")' for t in topic.include_any
        )
        parts.append(f"({any_clause})")
    if topic.include_all:
        all_clause = " AND ".join(
            f'(ti:"{t}" OR abs:"{t}")' for t in topic.include_all
        )
        parts.append(f"({all_clause})")
    return " AND ".join(parts) if parts else ""


def _parse_feed(xml_text: str, topic_name: str, days_back: int | None) -> list[Paper]:
    """Parse an arXiv Atom feed into Paper objects, optionally filtering by date."""
    papers: list[Paper] = []
    cutoff = (datetime.utcnow().date() - timedelta(days=days_back)) if days_back is not None else None
    root = ET.fromstring(xml_text)

    for entry in root.findall(f"{{{_ATOM_NS}}}entry"):
        try:
            # arXiv ID
            id_el = entry.find(f"{{{_ATOM_NS}}}id")
            raw_id = (id_el.text or "").strip() if id_el is not None else ""
            # e.g. http://arxiv.org/abs/2401.12345v1 → 2401.12345
            arxiv_id = raw_id.split("/abs/")[-1].split("v")[0] if raw_id else ""

            title_el = entry.find(f"{{{_ATOM_NS}}}title")
            title = " ".join((title_el.text or "").split()) if title_el is not None else ""

            summary_el = entry.find(f"{{{_ATOM_NS}}}summary")
            abstract = " ".join((summary_el.text or "").split()) if summary_el is not None else None

            # Authors
            authors: list[str] = []
            for author_el in entry.findall(f"{{{_ATOM_NS}}}author"):
                name_el = author_el.find(f"{{{_ATOM_NS}}}name")
                if name_el is not None and name_el.text:
                    authors.append(name_el.text.strip())

            # Published date
            pub_el = entry.find(f"{{{_ATOM_NS}}}published")
            date_str: str | None = None
            if pub_el is not None and pub_el.text:
                try:
                    pub_date = datetime.strptime(pub_el.text[:10], "%Y-%m-%d").date()
                    if cutoff and pub_date < cutoff:
                        continue  # outside the requested window
                    date_str = pub_date.isoformat()
                except ValueError:
                    pass

            # DOI (optional arXiv extension)
            doi_el = entry.find(f"{{{_ARXIV_NS}}}doi")
            doi = doi_el.text.strip() if doi_el is not None and doi_el.text else None

            # Category / journal_ref as venue proxy
            journal_ref_el = entry.find(f"{{{_ARXIV_NS}}}journal_ref")
            journal = journal_ref_el.text.strip() if journal_ref_el is not None and journal_ref_el.text else None
            if not journal:
                # Fall back to primary category
                cat_el = entry.find(f"{{{_ARXIV_NS}}}primary_category")
                if cat_el is not None:
                    journal = cat_el.get("term")

            url = f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else None

            papers.append(
                Paper(
                    source="arxiv",
                    source_id=f"arxiv:{arxiv_id}",
                    title=title,
                    abstract=abstract,
                    authors=authors,
                    published_date=date_str,
                    journal=journal,
                    doi=doi,
                    url=url,
                    topics_matched=[topic_name],
                )
            )
        except Exception as exc:
            logger.warning("Failed to parse arXiv entry: %s", exc)

    return papers


def fetch_arxiv(topic: Topic, days_back: int, max_results: int) -> list[Paper]:
    """Fetch papers from arXiv for a given topic.

    Returns an empty list on any network or parse error.
    """
    try:
        query = _build_query(topic)
        if not query:
            logger.warning("No query terms for topic %s — skipping arXiv", topic.name)
            return []

        params = {
            "search_query": query,
            "start": 0,
            "max_results": max_results,
            "sortBy": "relevance" if days_back is None else "submittedDate",
            "sortOrder": "descending",
        }

        logger.info("arXiv query: topic=%s query=%r", topic.name, query)
        resp = requests.get(_ARXIV_API, params=params, timeout=30)
        resp.raise_for_status()
        time.sleep(_SLEEP)

        return _parse_feed(resp.text, topic.name, days_back)

    except Exception as exc:
        logger.warning("arXiv fetch failed for topic %s: %s", topic.name, exc)
        return []
