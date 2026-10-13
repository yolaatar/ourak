"""Onboarding API routes — topic generation, first pass, and completion."""

import json
import logging
import os
import queue
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import yaml
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from app.db import (
    Feedback,
    PaperDB,
    PaperTopicLink,
    PresetDB,
    ProfileDB,
    TopicDB,
    UserDB,
    UserTopicSubscription,
    get_engine,
    get_session,
    mark_seen,
)
from app.dedup import dedup_papers
from app.models import Paper, Topic
from app.scoring import compute_term_boosts, score_paper, score_papers
from app.sources.arxiv import fetch_arxiv
from app.sources.biorxiv import fetch_biorxiv
from app.sources.paperswithcode import fetch_paperswithcode
from app.sources.semantic_scholar import fetch_semantic_scholar

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/onboarding", tags=["onboarding"])

_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


# --- Request / response models ---


class GenerateTopicsRequest(BaseModel):
    description: str
    seed_abstracts: list[str] = []


class TopicDict(BaseModel):
    name: str
    include_any: list[str] = []
    include_all: list[str] = []
    exclude: list[str] = []
    boost_authors: list[str] = []
    boost_venues: list[str] = []


class FirstPassRequest(BaseModel):
    topics: list[TopicDict]
    user_name: str = ""
    user_email: str = ""
    seed_abstracts: list[str] = []
    description: str = ""


class FeedbackItem(BaseModel):
    source_id: str
    signal: str  # "upvote" | "flag"


class CompleteRequest(BaseModel):
    user_name: str
    user_email: str = ""
    profile_name: str = ""
    topics: list[TopicDict]
    feedback: list[FeedbackItem] = []


# --- Helpers ---


_DEFAULT_SYSTEM = (
    "You are a research assistant configuring a paper-watching tool. "
    "Extract technical keywords from the user's research description "
    "and seed papers. Output ONLY valid YAML, no markdown fences, no explanation."
)


def _call_llm(prompt: str, system_prompt: str = _DEFAULT_SYSTEM, max_tokens: int = 1024) -> str:
    """Call OpenRouter and return the response content."""
    api_key = os.getenv("OPENROUTER_API_KEY")
    model = os.getenv("OPENROUTER_MODEL", "openai/gpt-oss-120b:free")

    if not api_key:
        raise HTTPException(status_code=500, detail="OPENROUTER_API_KEY not configured")

    resp = requests.post(
        _OPENROUTER_URL,
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.3,
        },
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        timeout=30,
    )
    if resp.status_code == 429:
        raise HTTPException(status_code=429, detail="LLM rate limited — wait a moment and try again")
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"].get("content")
    if not content:
        raise HTTPException(status_code=500, detail="LLM returned empty content — try again")
    return content.strip()


def _rerank_with_llm(papers: list, description: str, topics: list) -> list:
    """Re-rank papers by semantic relevance. Falls back to original order on any failure."""
    if len(papers) <= 1:
        return papers

    if description.strip():
        research_context = description.strip()
    else:
        keywords = []
        for t in topics:
            keywords.extend(t.include_any[:5])
            keywords.extend(t.include_all)
        research_context = "Research focused on: " + ", ".join(keywords)

    lines = []
    for i, p in enumerate(papers, 1):
        snippet = (p.abstract or "")[:250].replace("\n", " ")
        lines.append(f"{i}. {p.title}\n   {snippet}")

    prompt = (
        f"Re-rank these papers from most to least relevant for this researcher:\n\n"
        f"RESEARCH FOCUS:\n{research_context}\n\n"
        f"PAPERS:\n" + "\n\n".join(lines) + "\n\n"
        f"Output ONLY a comma-separated list of paper numbers ranked from most to least relevant.\n"
        f"Example: 3,1,7,5,2,4,6\nNo explanation, no other text."
    )

    system = (
        "You are a research paper relevance expert. "
        "Output ONLY a comma-separated list of integers. No explanation."
    )

    try:
        raw = _call_llm(prompt, system_prompt=system, max_tokens=128)
        indices = []
        for token in raw.replace("\n", ",").split(","):
            token = token.strip().strip(".")
            if token.isdigit():
                idx = int(token)
                if 1 <= idx <= len(papers) and idx not in indices:
                    indices.append(idx)
        if not indices:
            return papers
        reranked = [papers[i - 1] for i in indices]
        ranked_set = set(indices)
        for i in range(1, len(papers) + 1):
            if i not in ranked_set:
                reranked.append(papers[i - 1])
        return reranked
    except Exception as exc:
        logger.warning("LLM re-ranking failed, keeping keyword order: %s", exc)
        return papers


_FETCHER_NAMES = [
    ("arXiv", "fetch_arxiv"),
    ("Semantic Scholar", "fetch_semantic_scholar"),
    ("bioRxiv", "fetch_biorxiv"),
    ("Papers With Code", "fetch_paperswithcode"),
]

# Per-source max_results for calibration (relevance mode).
# S2 and arXiv have the best relevance ranking for computational papers.
_CALIBRATION_LIMITS = {
    "arXiv": 20,
    "Semantic Scholar": 30,
    "bioRxiv": 5,
    "Papers With Code": 10,
}

# Module reference for looking up fetcher functions (supports test patching)
import backend.api.onboarding as _self_module


def _get_fetchers():
    """Resolve fetcher functions at call time so mocks take effect."""
    return [(name, getattr(_self_module, attr)) for name, attr in _FETCHER_NAMES]


_RUNS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "runs")


def _save_run_log(body, topics, all_scored, sample):
    """Save a first-pass run to a JSON log file for later analysis."""
    try:
        os.makedirs(_RUNS_DIR, exist_ok=True)
        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        topic_names = [t.name for t in topics]
        log = {
            "timestamp": ts,
            "user_email": body.user_email,
            "topics": [t.model_dump() for t in topics],
            "total_papers_scored": len(all_scored),
            "sample_shown": [_paper_to_response(p) for p in sample],
            "all_papers": [_paper_to_response(p) for p in all_scored],
        }
        path = os.path.join(_RUNS_DIR, f"firstpass_{ts}.json")
        with open(path, "w") as f:
            json.dump(log, f, indent=2, default=str)
        logger.info("Saved first-pass run to %s (%d papers)", path, len(all_scored))
    except Exception as exc:
        logger.warning("Failed to save run log: %s", exc)


def _fetch_all_sources(topic: Topic, days_back: int = 30, max_results: int = 20) -> list[Paper]:
    """Fetch from all sources for a single topic (in parallel)."""
    fetchers = _get_fetchers()
    papers: list[Paper] = []
    with ThreadPoolExecutor(max_workers=len(fetchers)) as pool:
        futures = {pool.submit(fn, topic, days_back, max_results): name for name, fn in fetchers}
        for future in as_completed(futures):
            try:
                papers.extend(future.result())
            except Exception as exc:
                logger.warning("Source %s failed: %s", futures[future], exc)
    return papers


def _paper_to_response(paper: Paper) -> dict:
    """Convert a Pydantic Paper to a JSON-friendly dict."""
    return {
        "source": paper.source,
        "source_id": paper.source_id,
        "title": paper.title,
        "abstract": paper.abstract,
        "authors": paper.authors,
        "published_date": paper.published_date,
        "journal": paper.journal,
        "doi": paper.doi,
        "url": paper.url,
        "score": paper.score,
    }


# --- Endpoints ---


def _load_templates() -> str:
    """Load topic templates as YAML string for the LLM prompt."""
    templates_path = os.path.join(os.path.dirname(__file__), "..", "..", "config", "topic_templates.yaml")
    try:
        with open(templates_path) as f:
            return f.read()
    except FileNotFoundError:
        return "(no templates available)"


def _load_templates_parsed() -> list[dict]:
    """Load topic templates as parsed dicts."""
    templates_path = os.path.join(os.path.dirname(__file__), "..", "..", "config", "topic_templates.yaml")
    try:
        with open(templates_path) as f:
            data = yaml.safe_load(f)
        return data.get("templates", []) if isinstance(data, dict) else []
    except FileNotFoundError:
        return []


@router.get("/presets")
def get_presets(session: Session = Depends(get_session)) -> dict:
    """Return available topic presets: DB presets first, then YAML built-ins (deduplicated)."""
    presets = []
    seen_names: set[str] = set()

    # DB presets (user-created) — these take priority
    db_presets = session.exec(select(PresetDB)).all()
    for p in db_presets:
        # Look up creator username
        creator = None
        if p.user_id:
            user = session.get(UserDB, p.user_id)
            if user:
                creator = user.name
        presets.append({
            "id": p.id,
            "name": p.name,
            "description": p.description,
            "include_any": json.loads(p.include_any),
            "include_all": json.loads(p.include_all),
            "exclude": json.loads(p.exclude),
            "boost_authors": json.loads(p.boost_authors),
            "boost_venues": json.loads(p.boost_venues),
            "source": "custom",
            "created_by": creator,
        })
        seen_names.add(p.name)

    # YAML built-in templates — only add if not already in DB
    templates = _load_templates_parsed()
    for t in templates:
        name = t.get("name", "")
        if name in seen_names:
            continue
        presets.append({
            "id": None,
            "name": name,
            "description": t.get("description", ""),
            "include_any": t.get("include_any", []),
            "include_all": t.get("include_all", []),
            "exclude": t.get("exclude", []),
            "boost_authors": t.get("boost_authors", []),
            "boost_venues": t.get("boost_venues", []),
            "source": "builtin",
            "created_by": None,
        })
        seen_names.add(name)

    return {"presets": presets}


class PresetCreateRequest(BaseModel):
    name: str
    description: str = ""
    include_any: list[str] = []
    include_all: list[str] = []
    exclude: list[str] = []
    boost_authors: list[str] = []
    boost_venues: list[str] = []


@router.post("/presets")
def create_preset(
    body: PresetCreateRequest,
    request: Request,
    session: Session = Depends(get_session),
) -> dict:
    """Create a user-defined preset."""
    # Get user from JWT
    user_id = None
    from backend.auth import _get_secret
    from jose import jwt as jose_jwt
    token = request.cookies.get("session")
    if token:
        try:
            payload = jose_jwt.decode(token, _get_secret(), algorithms=["HS256"])
            username = payload.get("sub")
            user = session.exec(select(UserDB).where(UserDB.name == username)).first()
            if user:
                user_id = user.id
        except Exception:
            pass

    preset = PresetDB(
        user_id=user_id,
        name=body.name,
        description=body.description,
        include_any=json.dumps(body.include_any),
        include_all=json.dumps(body.include_all),
        exclude=json.dumps(body.exclude),
        boost_authors=json.dumps(body.boost_authors),
        boost_venues=json.dumps(body.boost_venues),
        is_builtin=False,
    )
    session.add(preset)
    session.commit()
    session.refresh(preset)
    return {"id": preset.id, "status": "ok"}


@router.delete("/presets/{preset_id}")
def delete_preset(
    preset_id: int,
    session: Session = Depends(get_session),
) -> dict:
    """Delete a user-created preset."""
    preset = session.get(PresetDB, preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")
    if preset.is_builtin:
        raise HTTPException(status_code=403, detail="Cannot delete built-in presets")
    session.delete(preset)
    session.commit()
    return {"status": "ok"}


@router.post("/generate-topics")
def generate_topics(body: GenerateTopicsRequest) -> dict:
    """Call LLM to generate topic configurations from a research description."""
    seed_text = "\n---\n".join(body.seed_abstracts) if body.seed_abstracts else "(none provided)"
    templates = _load_templates()

    prompt = f"""You have a library of pre-curated topic templates below. Your job:
1. Pick 2-4 templates that best match the user's research description
2. Adjust the keywords slightly to better fit their specific focus
3. You may add a few terms to include_any or remove irrelevant ones
4. You may create ONE new topic if none of the templates cover an important aspect

Output ONLY valid YAML in this exact format (no markdown fences):

topics:
  - name: slug-name
    include_any: [list of 10-20 specific compound phrases]
    include_all: [1-3 core terms that MUST appear in every matching paper]
    exclude: [5-10 terms from unrelated subfields]
    boost_authors: []
    boost_venues: [relevant journals]

=== TEMPLATE LIBRARY ===
{templates}

=== USER'S RESEARCH ===
{body.description}

=== SEED PAPER ABSTRACTS ===
{seed_text}

Rules:
- include_all should have 1-3 broad terms that define the topic's core focus (e.g. "segmentation", "electron microscopy"). Keep the template's include_all and adjust if needed for the user's niche.
- include_any should have 10-20 terms: specific multi-word phrases like "axon segmentation", "FIB-SEM", "connectome reconstruction" — NOT single generic words
- exclude should have 5-10 terms from clearly different fields
- Prefer reusing template keywords that are already well-tested
- Only adjust templates to better match the user's specific niche
- Output ONLY the YAML block"""

    raw = _call_llm(prompt)

    try:
        parsed = yaml.safe_load(raw)
    except yaml.YAMLError:
        raise HTTPException(status_code=500, detail="LLM returned invalid YAML")

    topics_raw = parsed.get("topics", []) if isinstance(parsed, dict) else []
    if not topics_raw:
        raise HTTPException(status_code=500, detail="No topics in LLM response")

    # Validate each topic against the Pydantic model
    validated = []
    for t in topics_raw:
        try:
            topic = Topic(**t)
            validated.append(topic.model_dump())
        except Exception:
            continue  # skip malformed topics

    if not validated:
        raise HTTPException(status_code=500, detail="No valid topics could be parsed")

    return {"topics": validated}


def _sse_event(data: dict) -> str:
    """Format a dict as an SSE data line."""
    return f"data: {json.dumps(data)}\n\n"


_SENTINEL = object()


@router.post("/run-first-pass")
def run_first_pass(body: FirstPassRequest):
    """Stream progress events as sources complete, then return papers."""
    topics = [Topic(**td.model_dump()) for td in body.topics]
    fetchers = [(name, fn) for name, fn in _get_fetchers() if _CALIBRATION_LIMITS.get(name, 20) > 0]
    total_jobs = len(topics) * len(fetchers)
    q: queue.Queue = queue.Queue()

    def _run_pool():
        """Run all fetches in a thread pool, push events to the queue."""
        all_papers: list[Paper] = []
        finished = 0

        with ThreadPoolExecutor(max_workers=total_jobs) as pool:
            futures = {}
            for topic in topics:
                for source_name, fn in fetchers:
                    limit = _CALIBRATION_LIMITS.get(source_name, 20)
                    future = pool.submit(fn, topic, None, limit)
                    futures[future] = (source_name, topic.name)

            for future in as_completed(futures):
                source_name, topic_name = futures[future]
                finished += 1
                try:
                    papers = future.result()
                    all_papers.extend(papers)
                    logger.info(
                        "✓ %s → %s: %d papers",
                        source_name, topic_name, len(papers),
                    )
                    q.put(_sse_event({
                        "type": "progress",
                        "source": source_name,
                        "topic": topic_name,
                        "status": "done",
                        "count": len(papers),
                        "finished": finished,
                        "total": total_jobs,
                    }))
                except Exception as exc:
                    logger.error(
                        "✗ %s → %s FAILED: %s", source_name, topic_name, exc,
                    )
                    q.put(_sse_event({
                        "type": "progress",
                        "source": source_name,
                        "topic": topic_name,
                        "status": "failed",
                        "error": str(exc),
                        "finished": finished,
                        "total": total_jobs,
                    }))

        # Dedup across all sources and topics
        raw_count = len(all_papers)
        all_papers = dedup_papers(all_papers)
        logger.info(
            "First pass: %d raw → %d after dedup", raw_count, len(all_papers),
        )

        # Filter out seed papers (papers whose abstract matches a pasted seed)
        if body.seed_abstracts:
            seed_snippets = [s[:200].lower() for s in body.seed_abstracts if s.strip()]
            all_papers = [
                p for p in all_papers
                if not any(
                    snippet in (p.abstract or "").lower()[:200]
                    for snippet in seed_snippets
                )
            ]

        # Score each paper against its best-matching topic and track assignment
        topic_buckets: dict[str, list[Paper]] = {t.name: [] for t in topics}
        for paper in all_papers:
            best_score = 0.0
            best_topic = topics[0].name
            for topic in topics:
                s = score_paper(paper, topic, use_recency=False)
                if s > best_score:
                    best_score = s
                    best_topic = topic.name
            paper.score = best_score
            topic_buckets[best_topic].append(paper)

        # Sort each bucket by score
        for name in topic_buckets:
            topic_buckets[name].sort(key=lambda p: p.score, reverse=True)

        # Round-robin pick from each topic to ensure fair representation
        n_topics = len(topics)
        per_topic = max(2, 10 // n_topics)
        sample: list[Paper] = []
        seen_ids: set[str] = set()
        # First pass: take top per_topic from each bucket
        for name in topic_buckets:
            for paper in topic_buckets[name][:per_topic]:
                if paper.source_id not in seen_ids:
                    sample.append(paper)
                    seen_ids.add(paper.source_id)
        # Fill remaining slots from all papers by score
        if len(sample) < 10:
            all_sorted = sorted(all_papers, key=lambda p: p.score, reverse=True)
            for paper in all_sorted:
                if paper.source_id not in seen_ids:
                    sample.append(paper)
                    seen_ids.add(paper.source_id)
                if len(sample) >= 10:
                    break
        # Final sort by keyword score, then LLM re-rank for semantic relevance
        sample.sort(key=lambda p: p.score, reverse=True)
        sample = _rerank_with_llm(sample, body.description, topics)

        # Log topic distribution in sample
        topic_counts = {}
        for name, bucket in topic_buckets.items():
            topic_counts[name] = len(bucket)
        logger.info(
            "Topic buckets: %s | Sample: %d papers",
            ", ".join(f"{k}={v}" for k, v in topic_counts.items()),
            len(sample),
        )

        # Persist all papers to DB (no topic/profile links yet)
        # so complete_onboarding doesn't need to re-fetch
        try:
            engine = get_engine()
            from sqlmodel import Session as DBSession
            with DBSession(engine) as db_session:
                mark_seen(db_session, all_papers)
                logger.info("Persisted %d papers to DB during first pass", len(all_papers))
        except Exception as exc:
            logger.warning("Failed to persist first-pass papers: %s", exc)

        # Save run to log for analysis
        _save_run_log(body, topics, all_papers, sample)

        q.put(_sse_event({
            "type": "results",
            "papers": [_paper_to_response(p) for p in sample],
        }))
        q.put(_SENTINEL)

    def _generate():
        worker = threading.Thread(target=_run_pool, daemon=True)
        worker.start()
        while True:
            item = q.get()
            if item is _SENTINEL:
                break
            yield item

    return StreamingResponse(_generate(), media_type="text/event-stream")


@router.post("/complete")
def complete_onboarding(
    body: CompleteRequest,
    session: Session = Depends(get_session),
) -> dict:
    """Create/find user, create profile, save topics, persist papers and feedback."""
    # 1. Find or create user
    existing = session.exec(select(UserDB).where(UserDB.name == body.user_name)).first()
    if existing:
        user = existing
    else:
        user = UserDB(name=body.user_name)
        session.add(user)
        session.commit()
        session.refresh(user)

    # 2. Create profile
    from datetime import datetime, timezone as tz
    profile_name = body.profile_name or ", ".join(t.name for t in body.topics)
    profile = ProfileDB(user_id=user.id, name=profile_name, last_fetched_at=datetime.now(tz.utc))
    session.add(profile)
    session.commit()
    session.refresh(profile)

    # 3. Save topics + subscriptions linked to profile
    for topic_dict in body.topics:
        topic_data = topic_dict.model_dump()
        existing_topic = session.exec(
            select(TopicDB).where(TopicDB.name == topic_data["name"])
        ).first()

        if existing_topic:
            db_topic = existing_topic
            # Update config if changed
            db_topic.config_yaml = yaml.dump(topic_data)
        else:
            db_topic = TopicDB(
                name=topic_data["name"],
                config_yaml=yaml.dump(topic_data),
                is_lab_topic=False,
            )
            session.add(db_topic)
            session.commit()
            session.refresh(db_topic)

        session.add(UserTopicSubscription(
            user_id=user.id, topic_id=db_topic.id, profile_id=profile.id,
        ))

    session.commit()

    # 4. Link existing papers to profile (papers were persisted during run_first_pass)
    all_db_papers = session.exec(select(PaperDB)).all()
    for topic_dict in body.topics:
        topic = Topic(**topic_dict.model_dump())
        db_topic = session.exec(
            select(TopicDB).where(TopicDB.name == topic.name)
        ).first()
        if not db_topic:
            continue

        # Score each paper against this topic and link if relevant
        for paper_row in all_db_papers:
            p = Paper(
                source=paper_row.source,
                source_id=paper_row.source_id,
                title=paper_row.title or "",
                abstract=paper_row.abstract or "",
                authors=json.loads(paper_row.authors) if paper_row.authors else [],
                published_date=paper_row.published_date,
                journal=paper_row.journal,
                doi=paper_row.doi,
                url=paper_row.url,
            )
            s = score_paper(p, topic)
            if s <= 0:
                continue

            # Update score in DB if higher
            if s > (paper_row.score or 0):
                paper_row.score = s
                session.add(paper_row)

            # Create link to profile
            existing_link = session.exec(
                select(PaperTopicLink).where(
                    PaperTopicLink.paper_id == paper_row.id,
                    PaperTopicLink.topic_id == db_topic.id,
                    PaperTopicLink.profile_id == profile.id,
                )
            ).first()
            if not existing_link:
                session.add(PaperTopicLink(
                    paper_id=paper_row.id,
                    topic_id=db_topic.id,
                    profile_id=profile.id,
                ))

    session.commit()

    # 5. Save feedback
    for fb_item in body.feedback:
        paper_row = session.exec(
            select(PaperDB).where(PaperDB.source_id == fb_item.source_id)
        ).first()
        if paper_row:
            session.add(Feedback(
                user_id=user.id,
                paper_id=paper_row.id,
                signal=fb_item.signal,
            ))

    session.commit()

    # 6. Compute term boosts from feedback and re-score papers
    upvoted_ids = {f.source_id for f in body.feedback if f.signal == "upvote"}
    flagged_ids = {f.source_id for f in body.feedback if f.signal == "flag"}
    all_db_papers_map = {p.source_id: p for p in session.exec(select(PaperDB)).all()}

    def _to_paper(row: PaperDB) -> Paper:
        return Paper(
            source=row.source, source_id=row.source_id,
            title=row.title or "", abstract=row.abstract or "",
            authors=json.loads(row.authors) if row.authors else [],
            published_date=row.published_date, journal=row.journal,
            doi=row.doi, url=row.url,
        )

    for topic_dict in body.topics:
        topic = Topic(**topic_dict.model_dump())
        db_topic = session.exec(select(TopicDB).where(TopicDB.name == topic.name)).first()
        if not db_topic:
            continue

        upvoted = [_to_paper(all_db_papers_map[sid]) for sid in upvoted_ids if sid in all_db_papers_map]
        flagged  = [_to_paper(all_db_papers_map[sid]) for sid in flagged_ids  if sid in all_db_papers_map]
        boosts = compute_term_boosts(upvoted, flagged, topic)

        # Persist boosts in the subscription
        sub = session.exec(
            select(UserTopicSubscription).where(
                UserTopicSubscription.user_id == user.id,
                UserTopicSubscription.topic_id == db_topic.id,
                UserTopicSubscription.profile_id == profile.id,
            )
        ).first()
        if sub:
            sub.term_boosts = json.dumps(boosts)
            session.add(sub)

        if not boosts:
            continue

        # Re-score papers linked to this profile+topic with the adjusted weights
        links = session.exec(
            select(PaperTopicLink).where(
                PaperTopicLink.topic_id == db_topic.id,
                PaperTopicLink.profile_id == profile.id,
            )
        ).all()
        for link in links:
            paper_row = session.get(PaperDB, link.paper_id)
            if not paper_row:
                continue
            p = _to_paper(paper_row)
            new_score = score_paper(p, topic, term_boosts=boosts)
            paper_row.score = new_score
            session.add(paper_row)

    session.commit()

    return {"user_id": user.id, "profile_id": profile.id}
