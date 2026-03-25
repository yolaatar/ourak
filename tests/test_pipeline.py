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


@patch("app.sources.paperswithcode.fetch_paperswithcode", return_value=_fake_papers("pwc", 2))
@patch("app.sources.biorxiv.fetch_biorxiv", return_value=_fake_papers("biorxiv", 2))
@patch("app.sources.semantic_scholar.fetch_semantic_scholar", return_value=_fake_papers("semantic_scholar", 2))
@patch("app.sources.arxiv.fetch_arxiv", return_value=_fake_papers("arxiv", 2))
@patch("app.llm.summarize_papers", return_value={})
def test_full_pipeline(mock_llm, mock_ax, mock_s2, mock_bio, mock_pwc):
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
