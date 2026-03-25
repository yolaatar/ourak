"""Entry point for paper-watch."""

import logging
from datetime import datetime, timezone
from pathlib import Path

from app.config import load_config, load_env
from app.db import get_unseen_papers, init_db, mark_seen
from app.dedup import dedup_papers
from app.digest import build_digest
from app.llm import summarize_papers
from app.scoring import score_papers
from app.sources.arxiv import fetch_arxiv
from app.sources.biorxiv import fetch_biorxiv
from app.sources.paperswithcode import fetch_paperswithcode
from app.sources.pubmed import fetch_pubmed
from app.sources.semantic_scholar import fetch_semantic_scholar

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


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

        for topic in cfg.topics:
            papers = fetch_pubmed(topic, days, limit)
            papers += fetch_arxiv(topic, days, limit)
            papers += fetch_semantic_scholar(topic, days, limit)
            papers += fetch_biorxiv(topic, days, limit)
            papers += fetch_paperswithcode(topic, days, limit)
            papers = get_unseen_papers(session, papers)
            papers = dedup_papers(papers)
            papers = score_papers(papers, topic)
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
        logging.getLogger(__name__).info("Digest saved to %s", out_path)

        mark_seen(session, all_papers)


if __name__ == "__main__":
    run()
