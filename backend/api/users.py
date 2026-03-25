"""User API routes."""

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.db import UserDB, TopicDB, UserTopicSubscription, get_session

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/{user_id}")
def get_user(user_id: int, session: Session = Depends(get_session)) -> dict:
    """Return user profile with subscribed topics."""
    user = session.get(UserDB, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    subs = session.exec(
        select(UserTopicSubscription).where(UserTopicSubscription.user_id == user_id)
    ).all()

    topics = []
    for sub in subs:
        topic = session.get(TopicDB, sub.topic_id)
        if topic:
            topics.append({"id": topic.id, "name": topic.name, "is_lab_topic": topic.is_lab_topic})

    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "topics": topics,
    }
