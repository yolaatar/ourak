"""Fetches the NeuroPoly team page to build an alumni exclusion set.

Why this exists: OpenAlex affiliation strings are stale by nature — a paper an
alumnus publishes years after leaving the lab can still list "NeuroPoly" in
their affiliation, or their profile can carry it forward indefinitely. The
lab-watch author-matching (app/sources/openalex.py) has no way to know someone
has left, so it keeps tagging their new work as lab output forever. Cross-
referencing the team page's own Alumni section is the fix: exclude anyone
listed there from every match path (ORCID, OpenAlex ID, name, and the
affiliation-keyword fallback alike — a stale config/lab.yaml entry is the same
failure mode as a stale OpenAlex affiliation string).
"""

import logging

import requests
from bs4 import BeautifulSoup

from app.sources.openalex import _norm_name

logger = logging.getLogger(__name__)

_TEAM_URL = "https://neuro.polymtl.ca/team/README.html"
_ALUMNI_SECTION = "alumni"


def _parse_team_html(html_text: str) -> tuple[set[str], set[str]]:
    """Return (current_member_names, alumni_names), both normalized via _norm_name."""
    soup = BeautifulSoup(html_text, "html.parser")
    current: set[str] = set()
    alumni: set[str] = set()

    for heading in soup.find_all("h2"):
        section_name = heading.get_text(strip=True).rstrip("#").strip().lower()
        ul = heading.find_next_sibling("ul")
        if not ul:
            continue
        names = {_norm_name(li.get_text(" ", strip=True)) for li in ul.find_all("li")}
        names.discard("")
        if section_name == _ALUMNI_SECTION:
            alumni |= names
        else:
            current |= names

    return current, alumni


def fetch_team_roster(url: str = _TEAM_URL) -> tuple[set[str], set[str]]:
    """Fetch and parse the team page. Returns (current_member_names, alumni_names).

    Raises on network/parse failure — callers should fail open (treat as "no
    alumni known this run") rather than let a scraping hiccup break the pipeline.
    """
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return _parse_team_html(resp.text)
