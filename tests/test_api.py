"""Tests for API endpoints (papers, topics, users, onboarding)."""

import json
import os
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.models import Paper


@pytest.fixture
def client():
    """Authenticated TestClient with in-memory DB."""
    with patch.dict(os.environ, {
        "APP_PASSWORD": "testpass123",
        "JWT_SECRET": "test-secret-key",
        "DATABASE_URL": "sqlite://",
    }):
        from backend.main import create_app
        app = create_app()
        c = TestClient(app)
        c.post("/auth/login", json={"username": "testuser", "password": "testpass123"})
        yield c


@pytest.fixture
def seeded_client(client):
    """Client with a user, topic, paper, and subscription pre-seeded."""
    from backend.main import _engine
    from app.db import UserDB, TopicDB, PaperDB, UserTopicSubscription

    with Session(_engine) as session:
        # The login already created "testuser", so create a second user
        user = UserDB(name="Alice")
        session.add(user)
        session.commit()
        session.refresh(user)

        topic = TopicDB(name="axon-seg", config_yaml="include_any: [axon]", is_lab_topic=True)
        session.add(topic)
        session.commit()
        session.refresh(topic)

        sub = UserTopicSubscription(user_id=user.id, topic_id=topic.id)
        session.add(sub)

        paper = PaperDB(
            source="arxiv",
            source_id="arxiv:2603.12345",
            title="Axon Segmentation in EM",
            abstract="A deep learning method for axon segmentation.",
            authors=json.dumps(["Smith J", "Doe A"]),
            published_date="2026-03-20",
            journal="Nature Methods",
            score=15.0,
            url="https://arxiv.org/abs/2603.12345",
        )
        session.add(paper)
        session.commit()

    return client


# --- Topics ---


def test_get_topics_empty(client):
    resp = client.get("/topics")
    assert resp.status_code == 200


def test_get_topics_with_data(seeded_client):
    resp = seeded_client.get("/topics")
    assert resp.status_code == 200
    topics = resp.json()
    assert len(topics) >= 1
    assert any(t["name"] == "axon-seg" for t in topics)


def test_get_topic_by_id(seeded_client):
    resp = seeded_client.get("/topics/1")
    assert resp.status_code == 200


def test_get_topic_not_found(client):
    resp = client.get("/topics/999")
    assert resp.status_code == 404


# --- Papers ---


def test_get_papers(seeded_client):
    resp = seeded_client.get("/papers")
    assert resp.status_code == 200
    papers = resp.json()
    assert len(papers) >= 1
    assert papers[0]["title"] == "Axon Segmentation in EM"


def test_get_papers_with_topic_filter(seeded_client):
    resp = seeded_client.get("/papers", params={"topic_id": 1})
    assert resp.status_code == 200


def test_get_paper_by_id(seeded_client):
    resp = seeded_client.get("/papers/1")
    assert resp.status_code == 200
    assert resp.json()["source_id"] == "arxiv:2603.12345"


def test_get_paper_not_found(client):
    resp = client.get("/papers/999")
    assert resp.status_code == 404


def test_submit_feedback(seeded_client):
    from backend.main import _engine
    from app.db import UserDB
    with Session(_engine) as session:
        from sqlmodel import select
        user = session.exec(select(UserDB).where(UserDB.name == "Alice")).first()
        user_id = user.id

    resp = seeded_client.post("/papers/1/feedback", json={"user_id": user_id, "signal": "upvote"})
    assert resp.status_code == 200
    assert resp.json()["signal"] == "upvote"


def test_submit_feedback_upsert(seeded_client):
    """Second feedback for same user+paper should update, not duplicate."""
    from backend.main import _engine
    from app.db import UserDB
    with Session(_engine) as session:
        from sqlmodel import select
        user = session.exec(select(UserDB).where(UserDB.name == "Alice")).first()
        user_id = user.id

    seeded_client.post("/papers/1/feedback", json={"user_id": user_id, "signal": "upvote"})
    resp = seeded_client.post("/papers/1/feedback", json={"user_id": user_id, "signal": "flag"})
    assert resp.status_code == 200
    assert resp.json()["signal"] == "flag"


# --- Users ---


def test_get_user(seeded_client):
    from backend.main import _engine
    from app.db import UserDB
    with Session(_engine) as session:
        from sqlmodel import select
        user = session.exec(select(UserDB).where(UserDB.name == "Alice")).first()
        user_id = user.id

    resp = seeded_client.get(f"/users/{user_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Alice"
    assert "topics" in data


def test_get_user_not_found(client):
    resp = client.get("/users/999")
    assert resp.status_code == 404


# --- Auth ---


def test_auth_me(client):
    resp = client.get("/auth/me")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "testuser"


def test_auth_wrong_password():
    with patch.dict(os.environ, {
        "APP_PASSWORD": "testpass123",
        "JWT_SECRET": "test-secret-key",
        "DATABASE_URL": "sqlite://",
    }):
        from backend.main import create_app
        app = create_app()
        c = TestClient(app)
        resp = c.post("/auth/login", json={"username": "testuser", "password": "wrong"})
        assert resp.status_code == 401


# --- Onboarding ---


def test_generate_topics(client):
    """Should return topics (mocked LLM)."""
    mock_yaml = """topics:
  - name: test-topic
    include_any:
      - deep learning
    include_all: []
    exclude: []
    boost_authors: []
    boost_venues: []"""

    with patch("backend.api.onboarding._call_llm", return_value=mock_yaml):
        resp = client.post("/onboarding/generate-topics", json={
            "description": "I study deep learning for medical imaging",
            "seed_abstracts": [],
        })
    assert resp.status_code == 200
    data = resp.json()
    assert "topics" in data
    assert len(data["topics"]) >= 1
    assert data["topics"][0]["name"] == "test-topic"


def _parse_sse(response_text):
    """Parse SSE stream text and return the last 'results' event."""
    events = []
    for chunk in response_text.split("\n\n"):
        chunk = chunk.strip()
        if not chunk:
            continue
        for line in chunk.split("\n"):
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    return events


def test_run_first_pass(client):
    """Should stream progress events and return scored papers (mocked sources)."""
    fake_papers = [
        Paper(
            source="semantic_scholar", source_id="s2:99",
            title="Axon segmentation with deep learning",
            abstract="A method for axon segmentation in electron microscopy.",
            authors=["Smith J"],
            published_date="2026-03-20",
            topics_matched=["test"],
        )
    ]

    with patch("backend.api.onboarding.fetch_arxiv", return_value=fake_papers), \
         patch("backend.api.onboarding.fetch_semantic_scholar", return_value=[]), \
         patch("backend.api.onboarding.fetch_biorxiv", return_value=[]), \
         patch("backend.api.onboarding.fetch_paperswithcode", return_value=[]):
        resp = client.post("/onboarding/run-first-pass", json={
            "topics": [{"name": "test", "include_any": ["axon segmentation"], "include_all": [], "exclude": [], "boost_authors": [], "boost_venues": []}],
            "user_name": "Test",
        })
    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    progress_events = [e for e in events if e["type"] == "progress"]
    result_events = [e for e in events if e["type"] == "results"]
    assert len(progress_events) >= 1
    assert len(result_events) == 1
    assert len(result_events[0]["papers"]) >= 1


def test_complete_onboarding(client):
    """Should create user, profile, topics, and save feedback."""
    fake_papers = [
        Paper(
            source="arxiv", source_id="arxiv:99",
            title="Test paper",
            abstract="Abstract",
            authors=["A"],
            published_date="2026-03-20",
        )
    ]

    with patch("backend.api.onboarding._fetch_all_sources", return_value=fake_papers):
        resp = client.post("/onboarding/complete", json={
            "user_name": "Bob",
            "topics": [{"name": "test", "include_any": ["segmentation"], "include_all": [], "exclude": [], "boost_authors": [], "boost_venues": []}],
            "feedback": [{"source_id": "arxiv:99", "signal": "upvote"}],
        })
    assert resp.status_code == 200
    data = resp.json()
    assert "user_id" in data
    assert "profile_id" in data
    assert data["user_id"] >= 1
    assert data["profile_id"] >= 1


# --- Profiles ---


def test_list_profiles(client):
    resp = client.get("/profiles")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# --- Presets ---


def test_get_presets(client):
    resp = client.get("/onboarding/presets")
    assert resp.status_code == 200
    data = resp.json()
    assert "presets" in data


def test_create_and_delete_preset(client):
    resp = client.post("/onboarding/presets", json={
        "name": "custom-test",
        "description": "A test preset",
        "include_any": ["test term"],
        "include_all": [],
        "exclude": [],
    })
    assert resp.status_code == 200
    preset_id = resp.json()["id"]

    # Should appear in presets list
    resp = client.get("/onboarding/presets")
    names = [p["name"] for p in resp.json()["presets"]]
    assert "custom-test" in names

    # Delete it
    resp = client.delete(f"/onboarding/presets/{preset_id}")
    assert resp.status_code == 200
