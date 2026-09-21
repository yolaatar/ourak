"""Lab watcher: new papers from lab members and new papers citing the lab.

Usage:
    python -m app.lab_watch                 # fetch, post to Slack, mark as seen
    python -m app.lab_watch --dry-run       # print the digest, touch nothing
    python -m app.lab_watch --find "A" "B"  # look up ORCID/OpenAlex IDs for lab.yaml
"""

import argparse
import logging
import os
import sys
from pathlib import Path

import yaml
from sqlmodel import Session, select

from app.config import load_env
from app.db import TopicDB, get_unseen_papers, init_db, mark_seen
from app.dedup import dedup_papers
from app.digest import build_digest
from app.models import LabConfig, LabPaper
from app.slack import build_messages, post_to_slack
from app.sources.openalex import (
    fetch_citing_papers,
    fetch_lab_papers,
    fetch_lab_works,
    search_authors,
)

logger = logging.getLogger(__name__)

# Topics the lab papers are linked to, so they can be filtered in the web feed
AUTHORED_TOPIC = "lab-papers"
CITING_TOPIC = "citing-lab"


def load_lab_config(path: str = "config/lab.yaml") -> LabConfig:
    with open(path, encoding="utf-8") as f:
        return LabConfig(**yaml.safe_load(f))


def _get_or_create_topic(session: Session, name: str) -> TopicDB:
    topic = session.exec(select(TopicDB).where(TopicDB.name == name)).first()
    if not topic:
        topic = TopicDB(name=name, is_lab_topic=True)
        session.add(topic)
        session.commit()
        session.refresh(topic)
    return topic


def _newest_first(papers: list[LabPaper]) -> list[LabPaper]:
    return sorted(papers, key=lambda p: p.published_date or "", reverse=True)


def collect(cfg: LabConfig, session: Session) -> tuple[list[LabPaper], list[LabPaper]]:
    """Fetch, drop already-seen papers, and dedup. Returns (authored, citing)."""
    authored = fetch_lab_papers(cfg, cfg.lookback_days)

    lab_works = fetch_lab_works(cfg)
    logger.info("Lab has %d known works in OpenAlex", len(lab_works))
    citing = fetch_citing_papers(lab_works, cfg.lookback_days) if lab_works else []

    authored = dedup_papers(get_unseen_papers(session, authored))
    citing = dedup_papers(get_unseen_papers(session, citing))
    return _newest_first(authored), _newest_first(citing)


def run(config_path: str = "config/lab.yaml", dry_run: bool = False) -> tuple[int, int]:
    """Run one lab-watch pass. Returns (new authored, new citing) counts."""
    load_env()
    cfg = load_lab_config(config_path)
    db_url = os.getenv("DATABASE_URL") or "sqlite:///data/paperwatch.db"
    if db_url.startswith("sqlite:///data/"):
        Path("data").mkdir(exist_ok=True)
    engine = init_db(db_url)

    with Session(engine) as session:
        authored, citing = collect(cfg, session)
        logger.info("New: %d lab papers, %d citing papers", len(authored), len(citing))

        if dry_run or not (authored or citing):
            print(build_digest([("New from the lab", authored), ("Citing the lab", citing)]))
            return len(authored), len(citing)

        webhook = os.getenv("SLACK_WEBHOOK_URL")
        if webhook:
            post_to_slack(webhook, build_messages(cfg.lab_name, authored, citing))
        else:
            logger.warning("SLACK_WEBHOOK_URL not set, printing digest instead")
            print(build_digest([("New from the lab", authored), ("Citing the lab", citing)]))

        # Only mark as seen once delivery succeeded, so a failed post is retried next run
        mark_seen(session, authored, topic_id=_get_or_create_topic(session, AUTHORED_TOPIC).id)
        mark_seen(session, citing, topic_id=_get_or_create_topic(session, CITING_TOPIC).id)

    return len(authored), len(citing)


def _print_author_matches(names: list[str]) -> None:
    load_env()
    for name in names:
        print(f"\n== {name}")
        for a in search_authors(name):
            inst = ", ".join(i["display_name"] for i in a.get("last_known_institutions") or [])
            print(
                f"{a['id'].rsplit('/', 1)[-1]:<14} works={a.get('works_count', 0):<5} "
                f"orcid={(a.get('orcid') or '-').rsplit('/', 1)[-1]:<20} "
                f"{a['display_name']}  [{inst}]"
            )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    sys.stdout.reconfigure(encoding="utf-8")  # author names break cp1252 on Windows
    parser = argparse.ArgumentParser(description="Watch for new lab papers and citations.")
    parser.add_argument("--config", default="config/lab.yaml")
    parser.add_argument("--dry-run", action="store_true", help="print only, don't post or mark seen")
    parser.add_argument("--find", metavar="NAME", nargs="+", help="search OpenAlex author profiles by name(s)")
    args = parser.parse_args()

    if args.find:
        _print_author_matches(args.find)
    else:
        run(args.config, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
