"""Tests for SQLite database layer."""

import json
from datetime import datetime, timezone

import pytest
from sqlmodel import Session, select

from app.models import Paper


@pytest.fixture
def db_engine():
    """Create an in-memory SQLite database for testing."""
    from app.db import init_db
    engine = init_db("sqlite://")
    return engine


@pytest.fixture
def db_session(db_engine):
    """Provide a session scoped to the test."""
    with Session(db_engine) as session:
        yield session


# --- Table creation ---


def test_init_db_creates_tables(db_engine):
    """All tables should exist after init_db."""
    from sqlalchemy import inspect
    inspector = inspect(db_engine)
    table_names = inspector.get_table_names()
    assert "users" in table_names
    assert "topics" in table_names
    assert "papers" in table_names
    assert "user_topic_subscriptions" in table_names
    assert "feedback" in table_names


# --- User CRUD ---


def test_create_user(db_session):
    from app.db import UserDB
    user = UserDB(name="Alice", email="alice@lab.org")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    assert user.id is not None
    assert user.name == "Alice"
    assert user.created_at is not None


def test_user_email_unique(db_session):
    from app.db import UserDB
    db_session.add(UserDB(name="Alice", email="alice@lab.org"))
    db_session.commit()
    db_session.add(UserDB(name="Bob", email="alice@lab.org"))
    with pytest.raises(Exception):  # IntegrityError
        db_session.commit()


# --- Topic CRUD ---


def test_create_topic(db_session):
    from app.db import TopicDB
    topic = TopicDB(name="axon-seg", config_yaml="include_any: [axon]")
    db_session.add(topic)
    db_session.commit()
    db_session.refresh(topic)
    assert topic.id is not None
    assert topic.name == "axon-seg"


# --- Paper CRUD ---


def test_create_paper(db_session):
    from app.db import PaperDB
    paper = PaperDB(
        source="pubmed",
        source_id="pubmed:12345",
        title="Test Paper",
        abstract="An abstract.",
        authors=json.dumps(["Smith J", "Doe A"]),
        published_date="2026-03-20",
        score=15.0,
    )
    db_session.add(paper)
    db_session.commit()
    db_session.refresh(paper)
    assert paper.id is not None
    assert json.loads(paper.authors) == ["Smith J", "Doe A"]


def test_paper_source_id_unique(db_session):
    from app.db import PaperDB
    db_session.add(PaperDB(source="pubmed", source_id="pubmed:1", title="A"))
    db_session.commit()
    db_session.add(PaperDB(source="arxiv", source_id="pubmed:1", title="B"))
    with pytest.raises(Exception):
        db_session.commit()


# --- Subscriptions ---


def test_user_topic_subscription(db_session):
    from app.db import UserDB, TopicDB, UserTopicSubscription
    user = UserDB(name="Alice", email="alice@lab.org")
    topic = TopicDB(name="test-topic", config_yaml="")
    db_session.add(user)
    db_session.add(topic)
    db_session.commit()
    db_session.refresh(user)
    db_session.refresh(topic)

    sub = UserTopicSubscription(user_id=user.id, topic_id=topic.id)
    db_session.add(sub)
    db_session.commit()

    result = db_session.exec(
        select(UserTopicSubscription).where(UserTopicSubscription.user_id == user.id)
    ).all()
    assert len(result) == 1
    assert result[0].topic_id == topic.id


# --- Feedback ---


def test_create_feedback(db_session):
    from app.db import UserDB, PaperDB, Feedback
    user = UserDB(name="Alice", email="alice@lab.org")
    paper = PaperDB(source="pubmed", source_id="pubmed:1", title="Paper")
    db_session.add(user)
    db_session.add(paper)
    db_session.commit()
    db_session.refresh(user)
    db_session.refresh(paper)

    fb = Feedback(user_id=user.id, paper_id=paper.id, signal="upvote")
    db_session.add(fb)
    db_session.commit()
    db_session.refresh(fb)
    assert fb.signal == "upvote"


# --- Storage helpers ---


def test_is_seen(db_session):
    from app.db import PaperDB, is_seen
    assert is_seen(db_session, "pubmed:999") is False
    db_session.add(PaperDB(source="pubmed", source_id="pubmed:999", title="X"))
    db_session.commit()
    assert is_seen(db_session, "pubmed:999") is True


def test_get_unseen_papers(db_session):
    from app.db import PaperDB, get_unseen_papers
    # Pre-seed one seen paper
    db_session.add(PaperDB(source="pubmed", source_id="pubmed:1", title="Seen"))
    db_session.commit()

    papers = [
        Paper(source="pubmed", source_id="pubmed:1", title="Seen"),
        Paper(source="pubmed", source_id="pubmed:2", title="Unseen"),
    ]
    unseen = get_unseen_papers(db_session, papers)
    assert len(unseen) == 1
    assert unseen[0].source_id == "pubmed:2"


def test_mark_seen(db_session):
    from app.db import mark_seen, is_seen
    papers = [
        Paper(source="pubmed", source_id="pubmed:10", title="A"),
        Paper(source="arxiv", source_id="arxiv:20", title="B", alt_ids=["s2:30"]),
    ]
    mark_seen(db_session, papers)
    assert is_seen(db_session, "pubmed:10") is True
    assert is_seen(db_session, "arxiv:20") is True
    # alt_ids should also be marked
    assert is_seen(db_session, "s2:30") is True


def test_mark_seen_idempotent(db_session):
    """Marking a paper seen twice should not raise."""
    from app.db import mark_seen
    papers = [Paper(source="pubmed", source_id="pubmed:10", title="A")]
    mark_seen(db_session, papers)
    mark_seen(db_session, papers)  # should not raise
