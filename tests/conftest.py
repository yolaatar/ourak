"""Shared fixtures for paper-watch tests."""

import pytest

from app.models import Topic


@pytest.fixture
def sample_topic() -> Topic:
    """A representative topic for testing source fetchers."""
    return Topic(
        name="axon-segmentation-em",
        include_any=["axon segmentation", "myelin segmentation", "electron microscopy"],
        include_all=["segmentation"],
        exclude=["retina", "plant"],
        boost_authors=["Smith J"],
        boost_venues=["Nature Methods"],
    )


@pytest.fixture
def broad_topic() -> Topic:
    """A topic with only include_any terms, no include_all or exclude."""
    return Topic(
        name="test-broad",
        include_any=["deep learning", "neural network"],
        include_all=[],
        exclude=[],
    )
