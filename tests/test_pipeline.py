"""Integration test: full pipeline with mocked sources and in-memory DB."""

from unittest.mock import patch

from sqlmodel import Session

from app.models import Paper


def _fake_papers(source: str, n: int = 3) -> list[Paper]:
    return [
        Paper(
            source=source,
            source_id=f"{source}:{i}",
            title=f"Axon segmentation method {source}-{i}",
            abstract=f"We present a novel axon segmentation approach using electron microscopy.",
            authors=["Smith J"],
            published_date="2026-03-20",
        )
        for i in range(n)
    ]


def _fake_fetcher(source: str, n: int = 2):
    """A fetcher stand-in matching fn(topic, days_back, max_results) -> list[Paper]."""
    def fetch(topic, days_back, max_results):
        return _fake_papers(source, n)
    return fetch


# Patched on app.main's own namespace (where these names are actually looked
# up when run() executes), not on app.sources/app.sources.openalex_discovery —
# app.main does `from app.sources import ALL_FETCHERS`, and that list is built
# once at app.sources import time. If app.sources has already been imported
# elsewhere in the test session (e.g. by backend.api.profiles, which imports
# the same ALL_FETCHERS), patching the individual source modules no longer
# reaches the already-built list — it still holds the original, unpatched
# functions. Patching app.main.ALL_FETCHERS replaces the list app.main itself
# reads, regardless of import order anywhere else.
@patch(
    "app.main.ALL_FETCHERS",
    [
        ("arXiv", _fake_fetcher("arxiv")),
        ("Semantic Scholar", _fake_fetcher("semantic_scholar")),
        ("bioRxiv", _fake_fetcher("biorxiv")),
        ("Papers With Code", _fake_fetcher("pwc")),
    ],
)
@patch("app.main.fetch_cites_known_work", return_value=[])
@patch("app.main.resolve_seed_concepts", return_value=set())
@patch("app.fulltext.fetch_fulltext", return_value=None)
@patch("app.llm.summarize_papers", return_value={})
def test_full_pipeline(mock_llm, mock_fulltext, mock_concepts, mock_citing):
    """Pipeline runs end-to-end with all sources, DB storage, and digest output."""
    from app.config import load_config
    from app.db import init_db, is_seen

    # Use in-memory DB
    engine = init_db("sqlite://")

    # Patch init_db in main to return our in-memory engine
    with patch("app.main.init_db", return_value=engine):
        with patch("app.main.load_env"):
            from app.main import run
            run()

    # Verify papers were persisted
    with Session(engine) as session:
        assert is_seen(session, "arxiv:0") is True
        assert is_seen(session, "semantic_scholar:0") is True
        assert is_seen(session, "biorxiv:0") is True
        assert is_seen(session, "pwc:0") is True

    # Run again — all papers should now be filtered as seen
    with patch("app.main.init_db", return_value=engine):
        with patch("app.main.load_env"):
            from app.main import run
            run()  # should produce empty digest without errors
