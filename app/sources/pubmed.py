"""PubMed source fetcher using NCBI E-utilities."""

import logging
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

import requests

from app.config import get_ncbi_api_key
from app.models import Paper, Topic

logger = logging.getLogger(__name__)

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

# 3 req/s unauthenticated; 10 req/s with API key
_SLEEP_UNAUTH = 0.34
_SLEEP_AUTH = 0.11


def _build_query(topic: Topic) -> str:
    """Construct a PubMed boolean query string from a Topic."""
    parts = []
    if topic.include_any:
        any_clause = " OR ".join(f'"{t}"[Title/Abstract]' for t in topic.include_any)
        parts.append(f"({any_clause})")
    if topic.include_all:
        all_clause = " AND ".join(f'"{t}"[Title/Abstract]' for t in topic.include_all)
        parts.append(f"({all_clause})")
    return " AND ".join(parts) if parts else ""


def _date_filter(days_back: int) -> tuple[str, str]:
    """Return (mindate, maxdate) strings for the NCBI date range filter."""
    today = datetime.utcnow().date()
    start = today - timedelta(days=days_back)
    return start.strftime("%Y/%m/%d"), today.strftime("%Y/%m/%d")


def _esearch(query: str, days_back: int | None, max_results: int, api_key: str | None) -> list[str]:
    """Run esearch and return a list of PubMed IDs."""
    params: dict = {
        "db": "pubmed",
        "term": query,
        "retmax": max_results,
        "retmode": "json",
        "usehistory": "n",
    }
    if days_back is not None:
        mindate, maxdate = _date_filter(days_back)
        params["mindate"] = mindate
        params["maxdate"] = maxdate
        params["datetype"] = "pdat"
    # When days_back is None, PubMed returns results by relevance (no date filter)
    if api_key:
        params["api_key"] = api_key

    resp = requests.get(ESEARCH_URL, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    return data.get("esearchresult", {}).get("idlist", [])


def _efetch(pmids: list[str], api_key: str | None) -> str:
    """Fetch full records for a list of PMIDs and return raw XML."""
    params: dict = {
        "db": "pubmed",
        "id": ",".join(pmids),
        "retmode": "xml",
        "rettype": "abstract",
    }
    if api_key:
        params["api_key"] = api_key

    resp = requests.get(EFETCH_URL, params=params, timeout=30)
    resp.raise_for_status()
    return resp.text


def _parse_xml(xml_text: str, topic_name: str) -> list[Paper]:
    """Parse PubMed XML into a list of Paper objects."""
    papers: list[Paper] = []
    root = ET.fromstring(xml_text)

    for article in root.findall(".//PubmedArticle"):
        try:
            medline = article.find("MedlineCitation")
            if medline is None:
                continue

            pmid_el = medline.find("PMID")
            pmid = pmid_el.text.strip() if pmid_el is not None and pmid_el.text else ""

            art = medline.find("Article")
            if art is None:
                continue

            title_el = art.find("ArticleTitle")
            title = "".join(title_el.itertext()).strip() if title_el is not None else ""

            # Abstract
            abstract_texts = art.findall(".//AbstractText")
            abstract = " ".join("".join(el.itertext()) for el in abstract_texts).strip() or None

            # Authors
            authors: list[str] = []
            for author in art.findall(".//Author"):
                last = author.findtext("LastName", "")
                fore = author.findtext("ForeName", "")
                name = f"{last} {fore}".strip()
                if name:
                    authors.append(name)

            # Journal
            journal_el = art.find("Journal/Title")
            journal = journal_el.text.strip() if journal_el is not None and journal_el.text else None

            # Published date
            pub_date = medline.find(".//PubDate")
            date_str: str | None = None
            if pub_date is not None:
                year = pub_date.findtext("Year", "")
                month = pub_date.findtext("Month", "01")
                day = pub_date.findtext("Day", "01")
                # Month may be abbreviated text; normalise to two digits if numeric
                try:
                    month_num = int(month)
                    date_str = f"{year}-{month_num:02d}-{int(day):02d}"
                except ValueError:
                    date_str = year if year else None

            # DOI
            doi: str | None = None
            for id_el in article.findall(".//ArticleId"):
                if id_el.get("IdType") == "doi" and id_el.text:
                    doi = id_el.text.strip()
                    break

            url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else None

            papers.append(
                Paper(
                    source="pubmed",
                    source_id=f"pubmed:{pmid}",
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
            logger.warning("Failed to parse PubMed article: %s", exc)

    return papers


def fetch_pubmed(topic: Topic, days_back: int, max_results: int) -> list[Paper]:
    """Fetch papers from PubMed for a given topic.

    Returns an empty list on any network or parse error.
    """
    try:
        api_key = get_ncbi_api_key()
        sleep_s = _SLEEP_AUTH if api_key else _SLEEP_UNAUTH

        query = _build_query(topic)
        if not query:
            logger.warning("No query terms for topic %s — skipping PubMed", topic.name)
            return []

        logger.info("PubMed esearch: topic=%s query=%r", topic.name, query)
        pmids = _esearch(query, days_back, max_results, api_key)
        if not pmids:
            return []

        time.sleep(sleep_s)

        logger.info("PubMed efetch: %d IDs for topic=%s", len(pmids), topic.name)
        xml_text = _efetch(pmids, api_key)
        time.sleep(sleep_s)

        return _parse_xml(xml_text, topic.name)

    except Exception as exc:
        logger.warning("PubMed fetch failed for topic %s: %s", topic.name, exc)
        return []
