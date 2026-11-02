"""Profile API routes."""

import json
import logging
import queue
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

import yaml
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from jose import jwt
from pydantic import BaseModel
from sqlmodel import Session, select

from app.db import (
    PaperDB,
    PaperTopicLink,
    ProfileDB,
    TopicDB,
    UserDB,
    UserTopicSubscription,
    get_engine,
    get_session,
    mark_seen,
)
from app.dedup import dedup_papers
from app.fulltext import apply_evidence_pass
from app.models import Paper, Topic
from app.scoring import score_paper, compute_term_boosts
from app.sources import ALL_FETCHERS
from app.sources.openalex_discovery import fetch_cites_known_work, resolve_seed_concepts

logger = logging.getLogger(__name__)

_FETCHERS = ALL_FETCHERS
_SOURCE_LIMITS = {
    "arXiv": 30, "Semantic Scholar": 50, "bioRxiv": 10,
    "Papers With Code": 15, "PubMed": 30, "OpenAlex": 30,
}
_EVIDENCE_BAND = (30.0, 65.0)
_MAX_FULLTEXT_CHECKS = 5
_SENTINEL = object()

router = APIRouter(prefix="/profiles", tags=["profiles"])


def _get_user(request: Request, session: Session) -> UserDB:
    """Extract the authenticated user from the JWT cookie."""
    from backend.auth import _get_secret
    token = request.cookies.get("session")
    payload = jwt.decode(token, _get_secret(), algorithms=["HS256"])
    username = payload.get("sub")
    user = session.exec(select(UserDB).where(UserDB.name == username)).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


@router.get("")
def list_profiles(
    request: Request,
    session: Session = Depends(get_session),
) -> list[dict]:
    """Return all profiles for the authenticated user."""
    user = _get_user(request, session)
    profiles = session.exec(
        select(ProfileDB)
        .where(ProfileDB.user_id == user.id)
        .order_by(ProfileDB.created_at.desc())
    ).all()

    result = []
    for p in profiles:
        # Count topics in this profile
        topic_count = len(session.exec(
            select(UserTopicSubscription).where(
                UserTopicSubscription.profile_id == p.id
            )
        ).all())
        result.append({
            "id": p.id,
            "name": p.name,
            "topic_count": topic_count,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "last_fetched_at": p.last_fetched_at.isoformat() if p.last_fetched_at else None,
        })
    return result


class RenameRequest(BaseModel):
    name: str


@router.patch("/{profile_id}")
def rename_profile(
    profile_id: int,
    body: RenameRequest,
    request: Request,
    session: Session = Depends(get_session),
) -> dict:
    """Rename a profile."""
    user = _get_user(request, session)
    profile = session.get(ProfileDB, profile_id)
    if not profile or profile.user_id != user.id:
        raise HTTPException(status_code=404, detail="Profile not found")
    profile.name = body.name
    session.commit()
    return {"status": "ok"}


@router.delete("/{profile_id}")
def delete_profile(
    profile_id: int,
    request: Request,
    session: Session = Depends(get_session),
) -> dict:
    """Delete a profile and its subscriptions/paper links."""
    user = _get_user(request, session)
    profile = session.get(ProfileDB, profile_id)
    if not profile or profile.user_id != user.id:
        raise HTTPException(status_code=404, detail="Profile not found")

    # Delete subscriptions and paper links for this profile
    subs = session.exec(
        select(UserTopicSubscription).where(UserTopicSubscription.profile_id == profile_id)
    ).all()
    for s in subs:
        session.delete(s)

    links = session.exec(
        select(PaperTopicLink).where(PaperTopicLink.profile_id == profile_id)
    ).all()
    for link in links:
        session.delete(link)

    session.delete(profile)
    session.commit()
    return {"status": "ok"}


@router.post("/{profile_id}/refresh")
def refresh_profile(
    profile_id: int,
    request: Request,
    session: Session = Depends(get_session),
):
    """Re-fetch papers for a profile's topics and stream progress via SSE."""
    user = _get_user(request, session)
    profile = session.get(ProfileDB, profile_id)
    if not profile or profile.user_id != user.id:
        raise HTTPException(status_code=404, detail="Profile not found")

    # Load topics for this profile
    subs = session.exec(
        select(UserTopicSubscription).where(UserTopicSubscription.profile_id == profile_id)
    ).all()
    topic_ids = [s.topic_id for s in subs]
    if not topic_ids:
        raise HTTPException(status_code=400, detail="Profile has no topics")

    topics: list[Topic] = []
    topic_db_map: dict[str, int] = {}
    topic_boosts_map: dict[str, dict] = {}
    for sub in subs:
        db_topic = session.get(TopicDB, sub.topic_id)
        if db_topic and db_topic.config_yaml:
            try:
                t = Topic(**yaml.safe_load(db_topic.config_yaml))
                topics.append(t)
                topic_db_map[t.name] = sub.topic_id
                topic_boosts_map[t.name] = json.loads(sub.term_boosts or "{}")
            except Exception:
                continue

    if not topics:
        raise HTTPException(status_code=400, detail="No valid topics found")

    # days_back: since last fetch + 1 day buffer, max 90 days
    if profile.last_fetched_at:
        delta = (datetime.now(timezone.utc) - profile.last_fetched_at.replace(tzinfo=timezone.utc)).days
        days_back = min(delta + 1, 90)
    else:
        days_back = 30

    total_jobs = len(topics) * len(_FETCHERS)
    q: queue.Queue = queue.Queue()

    def _sse(data: dict) -> str:
        return f"data: {json.dumps(data)}\n\n"

    def _run():
        all_papers: list[Paper] = []
        finished = 0

        with ThreadPoolExecutor(max_workers=total_jobs) as pool:
            futures = {}
            for topic in topics:
                for source_name, fn in _FETCHERS:
                    limit = _SOURCE_LIMITS.get(source_name, 20)
                    futures[pool.submit(fn, topic, days_back, limit)] = (source_name, topic.name)

            for future in as_completed(futures):
                source_name, topic_name = futures[future]
                finished += 1
                try:
                    papers = future.result()
                    all_papers.extend(papers)
                    q.put(_sse({"type": "progress", "source": source_name, "topic": topic_name,
                                "status": "done", "count": len(papers),
                                "finished": finished, "total": total_jobs}))
                except Exception as exc:
                    logger.warning("Refresh: %s → %s failed: %s", source_name, topic_name, exc)
                    q.put(_sse({"type": "progress", "source": source_name, "topic": topic_name,
                                "status": "failed", "finished": finished, "total": total_jobs}))

        # Papers citing something a topic's research already builds on
        # (topic.seed_works) — relevant independent of keyword overlap.
        # Resolved per-topic, outside the fetch pool since it's one or two
        # cheap OpenAlex calls rather than a per-source fetch.
        cites_ids_by_topic: dict[str, set[str]] = {}
        concepts_by_topic: dict[str, set[str]] = {}
        for topic in topics:
            if not topic.seed_works:
                continue
            try:
                citing = fetch_cites_known_work(topic.seed_works, days_back)
                all_papers.extend(citing)
                cites_ids_by_topic[topic.name] = {p.source_id for p in citing}
                concepts_by_topic[topic.name] = resolve_seed_concepts(topic.seed_works)
            except Exception as exc:
                logger.warning("seed_works lookup failed for topic %s: %s", topic.name, exc)

        all_papers = dedup_papers(all_papers)

        # Score, upsert, link to profile
        new_count = 0
        engine = get_engine()
        from sqlmodel import Session as DBSession
        with DBSession(engine) as db:
            mark_seen(db, all_papers)
            for topic in topics:
                topic_id = topic_db_map.get(topic.name)
                if not topic_id:
                    continue
                boosts = topic_boosts_map.get(topic.name) or None
                cites_ids = cites_ids_by_topic.get(topic.name, set())
                topic_concepts = concepts_by_topic.get(topic.name)

                # all_papers is shared across every topic in this loop, so
                # evidence_tier/snippet from a PREVIOUS topic's apply_evidence_pass
                # would otherwise leak into this topic's persisted row — reset
                # before (re)scoring each paper against this topic.
                scored: list[Paper] = []
                for paper in all_papers:
                    paper.evidence_tier = None
                    paper.evidence_snippet = None
                    paper.score = score_paper(
                        paper, topic, term_boosts=boosts,
                        topic_concepts=topic_concepts,
                        cites_known_work=paper.source_id in cites_ids,
                    )
                    if paper.score > 0:
                        paper.evidence_tier = "keyword_only"
                        scored.append(paper)

                apply_evidence_pass(
                    scored, topic,
                    evidence_band=_EVIDENCE_BAND, max_checks=_MAX_FULLTEXT_CHECKS,
                )

                for paper in scored:
                    s = paper.score
                    paper_row = db.exec(
                        select(PaperDB).where(PaperDB.source_id == paper.source_id)
                    ).first()
                    if not paper_row:
                        continue
                    if s > (paper_row.score or 0):
                        paper_row.score = s
                        if paper.evidence_tier:
                            paper_row.evidence_tier = paper.evidence_tier
                            paper_row.evidence_snippet = paper.evidence_snippet
                        db.add(paper_row)
                    exists = db.exec(
                        select(PaperTopicLink).where(
                            PaperTopicLink.paper_id == paper_row.id,
                            PaperTopicLink.topic_id == topic_id,
                            PaperTopicLink.profile_id == profile_id,
                        )
                    ).first()
                    if not exists:
                        db.add(PaperTopicLink(paper_id=paper_row.id, topic_id=topic_id, profile_id=profile_id))
                        new_count += 1

            # Update last_fetched_at
            profile_row = db.get(ProfileDB, profile_id)
            if profile_row:
                profile_row.last_fetched_at = datetime.now(timezone.utc)
                db.add(profile_row)
            db.commit()

        q.put(_sse({"type": "done", "new_papers": new_count}))
        q.put(_SENTINEL)

    def _generate():
        worker = threading.Thread(target=_run, daemon=True)
        worker.start()
        while True:
            item = q.get()
            if item is _SENTINEL:
                break
            yield item

    return StreamingResponse(_generate(), media_type="text/event-stream")
