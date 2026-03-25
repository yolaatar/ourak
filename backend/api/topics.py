"""Topic API routes."""

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.db import TopicDB, UserTopicSubscription, PaperDB, get_session

router = APIRouter(prefix="/topics", tags=["topics"])


@router.get("")
def list_topics(session: Session = Depends(get_session)) -> list[dict]:
    """Return all topics, lab topics first."""
    topics = session.exec(
        select(TopicDB).order_by(TopicDB.is_lab_topic.desc(), TopicDB.name)
    ).all()
    return [
        {
            "id": t.id,
            "name": t.name,
            "config_yaml": t.config_yaml,
            "is_lab_topic": t.is_lab_topic,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in topics
    ]


@router.get("/{topic_id}")
def get_topic(topic_id: int, session: Session = Depends(get_session)) -> dict:
    """Return a topic with subscriber count and recent paper count."""
    topic = session.get(TopicDB, topic_id)
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    sub_count = len(session.exec(
        select(UserTopicSubscription).where(UserTopicSubscription.topic_id == topic_id)
    ).all())

    return {
        "id": topic.id,
        "name": topic.name,
        "config_yaml": topic.config_yaml,
        "is_lab_topic": topic.is_lab_topic,
        "subscriber_count": sub_count,
        "created_at": topic.created_at.isoformat() if topic.created_at else None,
    }
