"""Tests for the lab watcher pipeline and Slack formatting."""

from unittest.mock import patch

import pytest
from sqlmodel import Session, select

import app.db as db
from app.db import PaperDB, TopicDB
from app.lab_watch import AUTHORED_TOPIC, CITING_TOPIC, run
from app.models import LabPaper
from app.slack import build_messages


def _paper(i, kind, **kw):
    return LabPaper(
        kind=kind,
        source="openalex",
        source_id=f"openalex:W{i}",
        title=f"Paper {i}",
        authors=["A. Author"],
        published_date=f"2026-09-{10 + i % 10:02d}",
        url=f"https://doi.org/10.1/{i}",
        **kw,
    )


# --- Slack formatting ---


def test_build_messages_sections_and_context():
    authored = [_paper(1, "authored", lab_authors=["Jane Lab"])]
    citing = [_paper(2, "citing", cited_lab_titles=["Our <great> paper"])]
    [msg] = build_messages("NeuroPoly", authored, citing)

    assert "1 new lab papers, 1 new citing papers" in msg["text"]
    texts = [b["text"]["text"] for b in msg["blocks"] if b["type"] == "section"]
    assert texts[0] == "*New from the lab*"
    assert "<https://doi.org/10.1/1|Paper 1>" in texts[1]
    assert "Lab: Jane Lab" in texts[1]
    assert texts[2] == "*Citing the lab*"
    assert "Cites: _Our &lt;great&gt; paper_" in texts[3]


def test_build_messages_skips_empty_section():
    [msg] = build_messages("NeuroPoly", [], [_paper(1, "citing")])
    texts = [b["text"]["text"] for b in msg["blocks"] if b["type"] == "section"]
    assert "*New from the lab*" not in texts


def test_build_messages_splits_over_block_limit():
    citing = [_paper(i, "citing") for i in range(60)]
    msgs = build_messages("NeuroPoly", [], citing)
    assert len(msgs) == 2
    assert all(len(m["blocks"]) <= 50 for m in msgs)
    assert sum(len(m["blocks"]) for m in msgs) == 60 + 3  # papers + header, divider, heading


def test_citing_titles_truncated_to_three():
    [msg] = build_messages("L", [], [_paper(1, "citing", cited_lab_titles=list("abcde"))])
    assert "(+2 more)" in msg["blocks"][-1]["text"]["text"]


# --- Pipeline ---


@pytest.fixture
def lab_env(tmp_path, monkeypatch):
    config = tmp_path / "lab.yaml"
    config.write_text(
        "lab_name: TestLab\nlookback_days: 30\nauthors:\n  - name: Jane\n    orcid: 0000-0001-0000-0001\n"
    )
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'lab.db'}")
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/test")
    return str(config)


@patch("app.lab_watch.post_to_slack")
@patch("app.lab_watch.fetch_citing_papers")
@patch("app.lab_watch.fetch_lab_works", return_value={"W100": "Old lab paper"})
@patch("app.lab_watch.fetch_lab_papers")
def test_run_posts_then_suppresses_seen(mock_lab, _works, mock_citing, mock_post, lab_env):
    mock_lab.side_effect = lambda *a: [_paper(1, "authored")]
    mock_citing.side_effect = lambda *a: [_paper(2, "citing"), _paper(3, "citing")]

    assert run(lab_env) == (1, 2)
    assert mock_post.call_count == 1

    # Same papers returned again: nothing new, nothing posted
    assert run(lab_env) == (0, 0)
    assert mock_post.call_count == 1


@patch("app.lab_watch.post_to_slack")
@patch("app.lab_watch.fetch_citing_papers", side_effect=lambda *a: [_paper(2, "citing")])
@patch("app.lab_watch.fetch_lab_works", return_value={"W100": "Old lab paper"})
@patch("app.lab_watch.fetch_lab_papers", side_effect=lambda *a: [_paper(1, "authored")])
def test_run_links_papers_to_lab_topics(_lab, _works, _citing, _post, lab_env):
    run(lab_env)

    with Session(db._engine) as s:
        topics = {t.name: t for t in s.exec(select(TopicDB)).all()}
        assert topics[AUTHORED_TOPIC].is_lab_topic and topics[CITING_TOPIC].is_lab_topic
        assert len(s.exec(select(PaperDB)).all()) == 2


@patch("app.lab_watch.post_to_slack", side_effect=RuntimeError("slack down"))
@patch("app.lab_watch.fetch_citing_papers", side_effect=lambda *a: [])
@patch("app.lab_watch.fetch_lab_works", return_value={})
@patch("app.lab_watch.fetch_lab_papers", side_effect=lambda *a: [_paper(1, "authored")])
def test_failed_post_does_not_mark_seen(_lab, _works, _citing, _post, lab_env):
    with pytest.raises(RuntimeError):
        run(lab_env)

    with Session(db._engine) as s:
        assert s.exec(select(PaperDB)).all() == []


@patch("app.lab_watch.post_to_slack")
@patch("app.lab_watch.fetch_citing_papers", side_effect=lambda *a: [])
@patch("app.lab_watch.fetch_lab_works", return_value={})
@patch("app.lab_watch.fetch_lab_papers", side_effect=lambda *a: [_paper(1, "authored")])
def test_dry_run_neither_posts_nor_marks_seen(_lab, _works, _citing, mock_post, lab_env):
    assert run(lab_env, dry_run=True) == (1, 0)
    assert run(lab_env, dry_run=True) == (1, 0)
    mock_post.assert_not_called()
