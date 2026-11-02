"""Tests for Papers With Code source fetcher."""

from unittest.mock import patch, MagicMock

import pytest

from app.models import Paper, Topic


# --- Fixtures ---

PWC_API_RESPONSE = {
    "count": 2,
    "next": None,
    "results": [
        {
            "id": "axon-seg-2026",
            "title": "Automated Axon Segmentation in Volume EM",
            "abstract": "We propose a novel deep learning method for segmentation of axons in electron microscopy.",
            "authors": ["Smith, J.", "Doe, A.", "Lee, C."],
            "published": "2026-03-20",
            "url_abs": "https://paperswithcode.com/paper/axon-seg-2026",
            "url_pdf": "https://arxiv.org/pdf/2603.99999.pdf",
            "proceeding": "MICCAI 2026",
            "repositories": [
                {"url": "https://github.com/user/axon-seg", "stars": 42}
            ],
        },
        {
            "id": "old-paper-2025",
            "title": "Some Old Paper",
            "abstract": "This paper is from last year.",
            "authors": ["Old, O."],
            "published": "2025-01-15",
            "url_abs": "https://paperswithcode.com/paper/old-paper-2025",
            "url_pdf": None,
            "proceeding": None,
            "repositories": [],
        },
    ],
}


# --- Tests ---


def test_build_query(sample_topic):
    """Query should join include_any terms."""
    from app.sources.paperswithcode import _build_query

    query = _build_query(sample_topic)
    assert "axon segmentation" in query
    assert "myelin segmentation" in query
    assert "electron microscopy" in query


def test_parse_results_filters_by_date(sample_topic):
    """Papers older than cutoff should be filtered out."""
    from app.sources.paperswithcode import _parse_results

    papers = _parse_results(PWC_API_RESPONSE, sample_topic.name, cutoff_date="2026-02-20")
    # Only the 2026-03-20 paper should pass; 2025-01-15 is too old
    assert len(papers) == 1
    assert papers[0].title == "Automated Axon Segmentation in Volume EM"


def test_parse_results_fields(sample_topic):
    """Verify parsed Paper has correct fields."""
    from app.sources.paperswithcode import _parse_results

    papers = _parse_results(PWC_API_RESPONSE, sample_topic.name, cutoff_date="2025-01-01")
    p = papers[0]
    assert p.source == "paperswithcode"
    assert p.source_id == "pwc:axon-seg-2026"
    assert p.published_date == "2026-03-20"
    assert p.journal == "MICCAI 2026"
    # Should prefer github URL if available
    assert "github.com" in p.url


def test_parse_results_no_github_url(sample_topic):
    """Paper without repos should use url_abs."""
    from app.sources.paperswithcode import _parse_results

    papers = _parse_results(PWC_API_RESPONSE, sample_topic.name, cutoff_date="2025-01-01")
    old_paper = papers[1]
    assert old_paper.url == "https://paperswithcode.com/paper/old-paper-2025"


def test_fetch_paperswithcode_success(sample_topic):
    """End-to-end fetch with mocked HTTP returns papers."""
    from app.sources.paperswithcode import fetch_paperswithcode

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = PWC_API_RESPONSE

    with patch("app.sources.paperswithcode.requests.get", return_value=mock_resp):
        with patch("app.sources.paperswithcode.time.sleep"):
            papers = fetch_paperswithcode(sample_topic, days_back=30, max_results=50)

    assert isinstance(papers, list)
    assert all(isinstance(p, Paper) for p in papers)


def test_fetch_paperswithcode_network_error(sample_topic):
    """Network error should return empty list."""
    from app.sources.paperswithcode import fetch_paperswithcode

    with patch("app.sources.paperswithcode.requests.get", side_effect=ConnectionError("fail")):
        papers = fetch_paperswithcode(sample_topic, days_back=30, max_results=50)

    assert papers == []
