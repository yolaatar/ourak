"""SQLite database layer using SQLModel."""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Generator

from sqlalchemy import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Field, Session, SQLModel, create_engine, select

from app.models import Paper

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///data/paperwatch.db")

_engine: Engine | None = None


# ──────────────────────────────────────────────
# Table definitions
# ──────────────────────────────────────────────

class UserDB(SQLModel, table=True):
    __tablename__ = "users"

    id: int | None = Field(default=None, primary_key=True)
    name: str
    email: str = Field(unique=True, index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TopicDB(SQLModel, table=True):
    __tablename__ = "topics"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    config_yaml: str = ""
    is_lab_topic: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PaperDB(SQLModel, table=True):
    __tablename__ = "papers"

    id: int | None = Field(default=None, primary_key=True)
    source: str
    source_id: str = Field(unique=True, index=True)
    title: str
    abstract: str | None = None
    authors: str = "[]"  # JSON-encoded list[str]
    published_date: str | None = None
    journal: str | None = None
    doi: str | None = None
    url: str | None = None
    score: float = 0.0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class UserTopicSubscription(SQLModel, table=True):
    __tablename__ = "user_topic_subscriptions"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id")
    topic_id: int = Field(foreign_key="topics.id")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PaperTopicLink(SQLModel, table=True):
    __tablename__ = "paper_topic_links"

    id: int | None = Field(default=None, primary_key=True)
    paper_id: int = Field(foreign_key="papers.id", index=True)
    topic_id: int = Field(foreign_key="topics.id", index=True)


class Feedback(SQLModel, table=True):
    __tablename__ = "feedback"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id")
    paper_id: int = Field(foreign_key="papers.id")
    signal: str  # "upvote" | "flag"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ──────────────────────────────────────────────
# Engine / session management
# ──────────────────────────────────────────────

def init_db(url: str | None = None) -> Engine:
    """Create the engine and all tables. Returns the engine."""
    global _engine
    resolved = url or DATABASE_URL
    if resolved == "sqlite://":
        # In-memory SQLite: share a single connection across threads
        _engine = create_engine(
            resolved,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    else:
        _engine = create_engine(resolved)
    SQLModel.metadata.create_all(_engine)
    return _engine


def get_session() -> Generator[Session, None, None]:
    """Yield a SQLModel session. Use as a FastAPI dependency or context manager."""
    if _engine is None:
        init_db()
    with Session(_engine) as session:
        yield session


# ──────────────────────────────────────────────
# Storage helpers (replacing app/storage.py)
# ──────────────────────────────────────────────

def is_seen(session: Session, source_id: str) -> bool:
    """Check if a paper with this source_id exists in the DB."""
    stmt = select(PaperDB).where(PaperDB.source_id == source_id)
    return session.exec(stmt).first() is not None


def get_unseen_papers(session: Session, papers: list[Paper]) -> list[Paper]:
    """Return only papers whose source_id is not already in the DB."""
    return [p for p in papers if not is_seen(session, p.source_id)]


def _upsert_paper(session: Session, paper: Paper) -> PaperDB:
    """Insert a paper into the DB, or return existing row."""
    existing = session.exec(
        select(PaperDB).where(PaperDB.source_id == paper.source_id)
    ).first()
    if existing:
        return existing
    row = PaperDB(
        source=paper.source,
        source_id=paper.source_id,
        title=paper.title,
        abstract=paper.abstract,
        authors=json.dumps(paper.authors),
        published_date=paper.published_date,
        journal=paper.journal,
        doi=paper.doi,
        url=paper.url,
        score=paper.score,
    )
    session.add(row)
    session.flush()
    return row


def mark_seen(session: Session, papers: list[Paper], topic_id: int | None = None) -> None:
    """Insert all papers (and their alt_ids) into the DB as seen.

    If topic_id is provided, also creates paper-topic links.
    """
    for paper in papers:
        row = _upsert_paper(session, paper)
        # Link paper to topic if provided
        if topic_id and row.id:
            existing_link = session.exec(
                select(PaperTopicLink).where(
                    PaperTopicLink.paper_id == row.id,
                    PaperTopicLink.topic_id == topic_id,
                )
            ).first()
            if not existing_link:
                session.add(PaperTopicLink(paper_id=row.id, topic_id=topic_id))
        # Also mark alt_ids so deduped variants don't resurface
        for alt_id in paper.alt_ids:
            if not is_seen(session, alt_id):
                session.add(PaperDB(
                    source=alt_id.split(":")[0] if ":" in alt_id else "unknown",
                    source_id=alt_id,
                    title=paper.title,
                    score=paper.score,
                ))
    session.commit()
