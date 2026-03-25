"""Paper API routes."""

import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, select

from app.db import PaperDB, PaperTopicLink, Feedback, UserTopicSubscription, get_session

router = APIRouter(prefix="/papers", tags=["papers"])


class FeedbackRequest(BaseModel):
    user_id: int
    signal: str  # "upvote" | "flag"


def _paper_to_dict(paper: PaperDB, feedback_signal: str | None = None) -> dict:
    """Convert a PaperDB row to a JSON-friendly dict."""
    return {
        "id": paper.id,
        "source": paper.source,
        "source_id": paper.source_id,
        "title": paper.title,
        "abstract": paper.abstract,
        "authors": json.loads(paper.authors) if paper.authors else [],
        "published_date": paper.published_date,
        "journal": paper.journal,
        "doi": paper.doi,
        "url": paper.url,
        "score": paper.score,
        "created_at": paper.created_at.isoformat() if paper.created_at else None,
        "feedback_signal": feedback_signal,
    }


@router.get("")
def list_papers(
    user_id: int | None = None,
    topic_id: int | None = None,
    sort_by: Literal["score", "date"] = "score",
    source: str | None = None,
    limit: int = 20,
    offset: int = 0,
    session: Session = Depends(get_session),
) -> list[dict]:
    """Return papers, optionally filtered by topic/source, sorted by score or date."""
    if topic_id:
        query = (
            select(PaperDB)
            .join(PaperTopicLink, PaperDB.id == PaperTopicLink.paper_id)
            .where(PaperTopicLink.topic_id == topic_id)
        )
    else:
        query = select(PaperDB)

    if source:
        query = query.where(PaperDB.source == source)

    if sort_by == "date":
        query = query.order_by(PaperDB.published_date.desc())
    else:
        query = query.order_by(PaperDB.score.desc())

    query = query.offset(offset).limit(limit)
    papers = session.exec(query).all()

    # Attach user feedback if user_id given
    results = []
    for paper in papers:
        signal = None
        if user_id:
            fb = session.exec(
                select(Feedback).where(
                    Feedback.user_id == user_id,
                    Feedback.paper_id == paper.id,
                )
            ).first()
            signal = fb.signal if fb else None
        results.append(_paper_to_dict(paper, signal))

    return results


@router.get("/{paper_id}")
def get_paper(paper_id: int, session: Session = Depends(get_session)) -> dict:
    """Return a single paper with feedback counts."""
    paper = session.get(PaperDB, paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    upvotes = len(session.exec(
        select(Feedback).where(Feedback.paper_id == paper_id, Feedback.signal == "upvote")
    ).all())
    flags = len(session.exec(
        select(Feedback).where(Feedback.paper_id == paper_id, Feedback.signal == "flag")
    ).all())

    result = _paper_to_dict(paper)
    result["upvote_count"] = upvotes
    result["flag_count"] = flags
    return result


@router.post("/{paper_id}/feedback")
def submit_feedback(
    paper_id: int,
    body: FeedbackRequest,
    session: Session = Depends(get_session),
) -> dict:
    """Upsert or remove feedback (one signal per user per paper).

    Send signal="remove" to delete existing feedback.
    """
    paper = session.get(PaperDB, paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    existing = session.exec(
        select(Feedback).where(
            Feedback.user_id == body.user_id,
            Feedback.paper_id == paper_id,
        )
    ).first()

    if body.signal == "remove":
        if existing:
            session.delete(existing)
            session.commit()
        return {"paper_id": paper_id, "user_id": body.user_id, "signal": None}

    if existing:
        existing.signal = body.signal
        session.add(existing)
    else:
        session.add(Feedback(
            user_id=body.user_id,
            paper_id=paper_id,
            signal=body.signal,
        ))

    session.commit()
    return {"paper_id": paper_id, "user_id": body.user_id, "signal": body.signal}
