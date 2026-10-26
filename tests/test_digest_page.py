"""Tests for the static discovery-digest HTML page."""

from app.digest_page import build_digest_page
from app.models import Paper


def _paper(i, **kw):
    return Paper(
        source="arxiv",
        source_id=f"arxiv:{i}",
        title=f"Paper {i}",
        authors=["A. Author"],
        url=f"https://doi.org/10.1/{i}",
        score=42.0,
        **kw,
    )


def test_renders_topics_and_papers():
    topic_results = [("axon-segmentation-em", [_paper(1), _paper(2)]), ("spinal-cord-mri", [])]
    html_out = build_digest_page(topic_results)

    assert "axon-segmentation-em" in html_out
    assert "2 papers" in html_out
    assert "Paper 1" in html_out
    assert "spinal-cord-mri" in html_out
    assert "No new papers found" in html_out


def test_empty_state_when_nothing_new():
    html_out = build_digest_page([("axon-segmentation-em", [])])
    assert "No new papers this week" in html_out


def test_summary_overrides_abstract():
    paper = _paper(1, abstract="the raw abstract")
    html_out = build_digest_page([("t", [paper])], summaries={"arxiv:1": "a short summary"})
    assert "a short summary" in html_out
    assert "the raw abstract" not in html_out


def test_evidence_tier_shown():
    paper = _paper(1, evidence_tier="confirmed", evidence_snippet="axons were segmented")
    html_out = build_digest_page([("t", [paper])])
    assert "Confirmed match" in html_out
    assert "axons were segmented" in html_out
