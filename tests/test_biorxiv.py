"""Tests for bioRxiv/medRxiv source fetcher."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

import pytest

from app.models import Paper, Topic


# --- Fixtures ---

BIORXIV_API_RESPONSE = {
    "messages": [{"status": "ok", "count": 2, "total": 2}],
    "collection": [
        {
            "doi": "10.1101/2026.03.01.000001",
            "title": "Automated axon segmentation in serial block-face electron microscopy",
            "authors": "Smith, J.; Doe, A.",
            "abstract": "We present a deep learning method for axon segmentation in SBEM volumes.",
            "date": "2026-03-15",
            "server": "biorxiv",
            "category": "neuroscience",
        },
        {
            "doi": "10.1101/2026.03.02.000002",
            "title": "Retinal cell classification from fundus images",
            "authors": "Jones, B.",
            "abstract": "A study on retinal imaging using deep learning.",
            "date": "2026-03-10",
            "server": "biorxiv",
            "category": "bioinformatics",
        },
        {
            "doi": "10.1101/2026.03.03.000003",
            "title": "Plant root segmentation with electron microscopy",
            "authors": "Lee, C.",
            "abstract": "Segmentation of plant root cells in electron microscopy images.",
            "date": "2026-03-12",
            "server": "biorxiv",
            "category": "plant biology",
        },
    ],
}


# --- Tests ---


def test_build_date_interval():
    from app.sources.biorxiv import _build_date_interval

    result = _build_date_interval(30)
    parts = result.split("/")
    assert len(parts) == 2
    start = datetime.strptime(parts[0], "%Y-%m-%d").date()
    end = datetime.strptime(parts[1], "%Y-%m-%d").date()
    assert (end - start).days == 30


def test_matches_topic_positive(sample_topic):
    """Paper about axon segmentation + EM should match."""
    from app.sources.biorxiv import _matches_topic

    item = {
        "title": "Automated axon segmentation in SBEM",
        "abstract": "Deep learning for segmentation of myelinated axons.",
    }
    assert _matches_topic(item, sample_topic) is True


def test_matches_topic_exclude(sample_topic):
    """Paper mentioning 'retina' should be excluded even if include_any matches."""
    from app.sources.biorxiv import _matches_topic

    item = {
        "title": "Segmentation of retina cells using electron microscopy",
        "abstract": "We segment retinal neurons in EM volumes.",
    }
    assert _matches_topic(item, sample_topic) is False


def test_matches_topic_missing_include_all(sample_topic):
    """Paper matching include_any but missing include_all should be excluded."""
    from app.sources.biorxiv import _matches_topic

    item = {
        "title": "Electron microscopy of protein crystals",
        "abstract": "We image protein structures using cryo-EM.",
    }
    # include_all requires "segmentation" — this paper doesn't have it
    assert _matches_topic(item, sample_topic) is False


def test_parse_results(sample_topic):
    """Parse API JSON into Paper objects with correct fields."""
    from app.sources.biorxiv import _parse_results

    papers = _parse_results(BIORXIV_API_RESPONSE, "biorxiv", sample_topic)
    # Only the first paper should match (axon segmentation + segmentation in abstract)
    # Second is excluded by "retina", third by "plant"
    assert len(papers) == 1
    p = papers[0]
    assert p.source == "biorxiv"
    assert p.source_id == "biorxiv:10.1101/2026.03.01.000001"
    assert "axon segmentation" in p.title.lower()
    assert p.authors == ["Smith J", "Doe A"]
    assert p.published_date == "2026-03-15"
    assert p.url == "https://doi.org/10.1101/2026.03.01.000001"


def test_fetch_biorxiv_success(sample_topic):
    """End-to-end fetch with mocked HTTP returns papers."""
    from app.sources.biorxiv import fetch_biorxiv

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = BIORXIV_API_RESPONSE

    with patch("app.sources.biorxiv.requests.get", return_value=mock_resp):
        with patch("app.sources.biorxiv.time.sleep"):
            papers = fetch_biorxiv(sample_topic, days_back=30, max_results=50)

    assert isinstance(papers, list)
    assert all(isinstance(p, Paper) for p in papers)


def test_fetch_biorxiv_network_error(sample_topic):
    """Network error should return empty list, not crash."""
    from app.sources.biorxiv import fetch_biorxiv

    with patch("app.sources.biorxiv.requests.get", side_effect=ConnectionError("timeout")):
        papers = fetch_biorxiv(sample_topic, days_back=30, max_results=50)

    assert papers == []
