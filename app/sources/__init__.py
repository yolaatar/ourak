"""Single source of truth for which fetchers the discovery pipeline runs.

app/main.py and backend/api/profiles.py both used to hardcode their own copy
of this list, which could silently drift. Add a new source here once and
both call sites pick it up.

Each fetcher is `(display_name, fn)` where `fn(topic, days_back, max_results)
-> list[Paper]`.
"""

from app.sources.arxiv import fetch_arxiv
from app.sources.biorxiv import fetch_biorxiv
from app.sources.openalex_discovery import fetch_openalex
from app.sources.paperswithcode import fetch_paperswithcode
from app.sources.pubmed import fetch_pubmed
from app.sources.semantic_scholar import fetch_semantic_scholar

ALL_FETCHERS: list[tuple[str, callable]] = [
    ("arXiv", fetch_arxiv),
    ("Semantic Scholar", fetch_semantic_scholar),
    ("bioRxiv", fetch_biorxiv),
    ("Papers With Code", fetch_paperswithcode),
    ("PubMed", fetch_pubmed),
    ("OpenAlex", fetch_openalex),
]
