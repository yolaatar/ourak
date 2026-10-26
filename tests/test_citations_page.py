"""Tests for the static citations digest page generator."""

import pytest
from sqlmodel import Session

from app.citations_page import build_citations_page
from app.db import mark_seen
from app.lab_watch import CITING_TOPIC
from app.models import LabPaper


@pytest.fixture
def db_session():
    from app.db import init_db
    engine = init_db("sqlite://")
    with Session(engine) as session:
        yield session


def _work(title, authors=None, published_date=None, is_first_author=False, lab_coauthors=None):
    return {
        "title": title,
        "authors": authors or [],
        "published_date": published_date,
        "is_first_author": is_first_author,
        "lab_coauthors": lab_coauthors or [],
    }


def _citing(i, cited_lab_works, published_date="2026-09-01"):
    return LabPaper(
        kind="citing",
        source="openalex",
        source_id=f"openalex:W{i}",
        title=f"Citing paper {i}",
        authors=["A. Author"],
        journal="Some Journal",
        published_date=published_date,
        url=f"https://doi.org/10.1/{i}",
        cited_lab_works=cited_lab_works,
    )


def _link_to_citing_topic(db_session):
    from app.db import TopicDB, PaperTopicLink, PaperDB
    from sqlmodel import select

    topic = TopicDB(name=CITING_TOPIC, is_lab_topic=True)
    db_session.add(topic)
    db_session.commit()
    db_session.refresh(topic)
    for row in db_session.exec(select(PaperDB)).all():
        db_session.add(PaperTopicLink(paper_id=row.id, topic_id=topic.id))
    db_session.commit()


def test_groups_by_cited_title(db_session):
    sct = _work("SCT: Spinal Cord Toolbox", authors=["J. Cohen-Adad", "B. De Leener"], published_date="2017-01-05")
    axon = _work("AxonDeepSeg", authors=["A. Zaimi"], published_date="2018-06-01")
    papers = [
        _citing(1, [sct]),
        _citing(2, [sct]),
        _citing(3, [axon]),
    ]
    mark_seen(db_session, papers, topic_id=None)
    _link_to_citing_topic(db_session)

    html_out = build_citations_page(db_session, "NeuroPoly")

    assert "SCT: Spinal Cord Toolbox" in html_out
    assert "2 citations" in html_out
    assert "AxonDeepSeg" in html_out
    assert "1 citation<" in html_out
    assert "Citing paper 1" in html_out
    # the cited-work meta row: authors + date under its title
    assert "J. Cohen-Adad, B. De Leener · 2017-01-05" in html_out


def test_empty_state_when_no_citations(db_session):
    html_out = build_citations_page(db_session, "NeuroPoly")
    assert "No citations tracked yet" in html_out


def test_lab_led_work_outranks_higher_citation_count(db_session):
    # "consortium" is cited far more, but a lab member is only a minor co-author
    # on it — "axon" is lab-led and should still come first
    consortium = _work("Big Consortium Paper", is_first_author=False)
    axon = _work("AxonDeepSeg", authors=["A. Zaimi"], is_first_author=True)
    papers = [_citing(i, [consortium]) for i in range(5)] + [_citing(10, [axon])]
    mark_seen(db_session, papers, topic_id=None)
    _link_to_citing_topic(db_session)

    html_out = build_citations_page(db_session, "NeuroPoly")

    assert html_out.index("AxonDeepSeg") < html_out.index("Big Consortium Paper")
    assert "Lab-led" in html_out


def test_shows_lab_coauthor_when_not_lab_led(db_session):
    # PI buried past the "et al." cutoff on an outside consortium paper — not
    # lab-led, but should still be called out since otherwise invisible
    consortium = _work(
        "Big Consortium Paper",
        authors=["Outsider One", "Outsider Two", "Outsider Three", "Julien Cohen-Adad"],
        is_first_author=False,
        lab_coauthors=["Julien Cohen-Adad"],
    )
    mark_seen(db_session, [_citing(1, [consortium])], topic_id=None)
    _link_to_citing_topic(db_session)

    html_out = build_citations_page(db_session, "NeuroPoly")

    assert 'class="groupCoauthor">Lab: Julien Cohen-Adad<' in html_out


def test_no_coauthor_line_when_lab_led():
    from app.citations_page import _group_html

    axon = _work("AxonDeepSeg", authors=["A. Zaimi"], is_first_author=True, lab_coauthors=["A. Zaimi"])
    assert "groupCoauthor" not in _group_html(axon, [])


def test_grouped_by_month_newest_first(db_session):
    axon = _work("AxonDeepSeg")
    papers = [
        _citing(1, [axon], published_date="2026-08-15"),
        _citing(2, [axon], published_date="2026-09-10"),
    ]
    mark_seen(db_session, papers, topic_id=None)
    _link_to_citing_topic(db_session)

    html_out = build_citations_page(db_session, "NeuroPoly")

    assert "September 2026" in html_out
    assert "August 2026" in html_out
    assert html_out.index("September 2026") < html_out.index("August 2026")
