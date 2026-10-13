"""Entry point for paper-watch."""

import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from app.config import load_config, load_env
from app.db import get_unseen_papers, init_db, mark_seen
from app.dedup import dedup_papers
from app.digest import build_digest
from app.fulltext import apply_evidence_pass
from app.llm import summarize_papers
from app.scoring import score_papers
from app.slack import build_digest_messages, post_to_slack
from app.sources import ALL_FETCHERS
from app.sources.openalex_discovery import fetch_cites_known_work, resolve_seed_concepts

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def run() -> None:
    """Fetch, score, and print a markdown digest of new research papers."""
    load_env()
    cfg = load_config("config")
    engine = init_db()

    from sqlmodel import Session

    with Session(engine) as session:
        topic_results: list[tuple[str, list]] = []
        days = cfg.defaults["days_back"]
        limit = cfg.defaults["max_results_per_source"]
        evidence_band = tuple(cfg.defaults.get("evidence_band", [30, 65]))
        max_fulltext_checks = cfg.defaults.get("max_fulltext_checks", 5)

        for topic in cfg.topics:
            papers = []
            for name, fetch in ALL_FETCHERS:
                try:
                    papers += fetch(topic, days, limit)
                except Exception as exc:
                    logger.warning("%s fetch failed for topic %s: %s", name, topic.name, exc)

            # Papers citing something this research already builds on
            # (topic.seed_works) — relevant independent of keyword overlap.
            citing_known_work = fetch_cites_known_work(topic.seed_works, days)
            papers += citing_known_work
            cites_known_work_ids = {p.source_id for p in citing_known_work}
            topic_concepts = resolve_seed_concepts(topic.seed_works)

            papers = get_unseen_papers(session, papers)
            papers = dedup_papers(papers)
            papers = score_papers(
                papers, topic,
                topic_concepts=topic_concepts,
                cites_known_work_ids=cites_known_work_ids,
            )
            apply_evidence_pass(papers, topic, evidence_band=evidence_band, max_checks=max_fulltext_checks)
            papers = sorted(papers, key=lambda p: p.score, reverse=True)[: cfg.defaults["top_k"]]
            topic_results.append((topic.name, papers))

        all_papers = [p for _, papers in topic_results for p in papers]
        summaries: dict[str, str] = {}
        if cfg.defaults.get("summarize"):
            summaries = summarize_papers(all_papers)

        digest = build_digest(topic_results, summaries)
        print(digest)

        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M")
        out_path = Path("data") / f"digest_{timestamp}.md"
        out_path.write_text(digest)
        logger.info("Digest saved to %s", out_path)

        webhook = os.getenv("SLACK_WEBHOOK_URL")
        if webhook:
            try:
                post_to_slack(webhook, build_digest_messages(topic_results))
            except Exception as exc:
                logger.warning("Slack delivery failed: %s", exc)
        else:
            logger.info("SLACK_WEBHOOK_URL not set, skipping Slack delivery")

        mark_seen(session, all_papers)


if __name__ == "__main__":
    run()
