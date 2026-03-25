"""LLM summarization via OpenRouter (openai-compatible chat completions)."""

import logging
import os
import time

import requests

from app.models import Paper

logger = logging.getLogger(__name__)

_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_MODEL = "openai/gpt-oss-120b:free"
_SLEEP = 3.0  # free tier is rate-limited; be conservative


def _get_api_key() -> str | None:
    return os.getenv("OPENROUTER_API_KEY") or None


_SYSTEM_PROMPT = (
    "You are a research assistant. Given a paper title and abstract, "
    "write exactly one concise sentence (max 30 words) summarizing the key contribution. "
    "Be specific — mention the method or dataset if notable. No preamble."
)


def _summarize_one(title: str, abstract: str, api_key: str) -> str:
    """Call OpenRouter and return a one-sentence summary."""
    user_msg = f"Title: {title}\n\nAbstract: {abstract[:1200]}"
    payload = {
        "model": _MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        "max_tokens": 512,
        "temperature": 0.3,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/paper-watch",
    }
    resp = requests.post(_OPENROUTER_URL, json=payload, headers=headers, timeout=20)
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"].get("content")
    if not content:
        raise ValueError("Empty content in response (model may have only returned reasoning)")
    return content.strip()


def summarize_papers(papers: list[Paper]) -> dict[str, str]:
    """Return a dict mapping source_id -> one-sentence summary for each paper.

    Skips papers without an abstract. Returns an empty dict if no API key is set
    or if all requests fail — callers should treat missing keys as no summary.
    """
    api_key = _get_api_key()
    if not api_key:
        logger.warning("OPENROUTER_API_KEY not set — skipping summarization")
        return {}

    summaries: dict[str, str] = {}
    for paper in papers:
        if not paper.abstract:
            continue
        try:
            summary = _summarize_one(paper.title, paper.abstract, api_key)
            summaries[paper.source_id] = summary
            logger.debug("Summarized %s", paper.source_id)
            time.sleep(_SLEEP)
        except Exception as exc:
            logger.warning("Summarization failed for %s: %s", paper.source_id, exc)

    return summaries
