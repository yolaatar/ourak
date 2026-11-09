"""Tests for relevance scoring, including the OpenAlex-derived signals
(concept overlap, cites-known-work, citation count) added alongside the
keyword-based score. All pure/offline — these signals are resolved by the
caller (see app/sources/openalex_discovery.py) and passed in, so scoring
itself never touches the network.
"""

from datetime import datetime, timedelta, timezone

from app.models import Paper, Topic
from app.scoring import score_paper, score_papers


def _topic(**overrides) -> Topic:
    defaults = dict(
        name="test-topic",
        include_any=["axon segmentation"],
        include_all=[],
        exclude=[],
        boost_authors=[],
        boost_venues=[],
    )
    defaults.update(overrides)
    return Topic(**defaults)


def _paper(**overrides) -> Paper:
    defaults = dict(
        source="arxiv",
        source_id="arxiv:1",
        title="A paper about axon segmentation",
        abstract="We study axon segmentation in microscopy.",
        authors=["A. Researcher"],
        published_date=None,
    )
    defaults.update(overrides)
    return Paper(**defaults)


def _days_ago(n: int) -> str:
    return (datetime.now(timezone.utc).date() - timedelta(days=n)).isoformat()


class TestConceptOverlap:
    def test_shared_concept_increases_score(self):
        topic = _topic()
        paper_with_concept = _paper(concepts=["Myelin"])
        paper_without = _paper(source_id="arxiv:2", concepts=[])

        with_score = score_paper(paper_with_concept, topic, use_recency=False, topic_concepts={"Myelin"})
        without_score = score_paper(paper_without, topic, use_recency=False, topic_concepts={"Myelin"})

        assert with_score > without_score

    def test_no_topic_concepts_is_a_noop(self):
        paper = _paper(concepts=["Myelin"])
        topic = _topic()
        # Should not raise, and should match the score with topic_concepts=None
        assert score_paper(paper, topic, use_recency=False, topic_concepts=None) == score_paper(
            paper, topic, use_recency=False
        )

    def test_concept_bonus_is_capped(self):
        topic = _topic()
        paper = _paper(concepts=["A", "B", "C", "D", "E", "F", "G", "H"])  # way more than the cap
        capped_score = score_paper(paper, topic, use_recency=False, topic_concepts={"A", "B", "C", "D", "E", "F", "G", "H"})
        # 8 concepts * 5.0 = 40 raw, but capped at +20 — verify against a paper
        # with exactly enough concepts to hit the cap (4 * 5.0 = 20)
        four_concepts_paper = _paper(source_id="arxiv:3", concepts=["A", "B", "C", "D"])
        four_score = score_paper(four_concepts_paper, topic, use_recency=False, topic_concepts={"A", "B", "C", "D"})
        assert capped_score == four_score


class TestCitesKnownWork:
    def test_cites_known_work_boosts_score(self):
        topic = _topic(include_any=[])  # no keyword signal at all
        paper = _paper(title="Unrelated title", abstract=None)
        with_bonus = score_paper(paper, topic, use_recency=False, cites_known_work=True)
        without_bonus = score_paper(paper, topic, use_recency=False, cites_known_work=False)
        assert with_bonus > without_bonus
        assert with_bonus > 0  # relevant purely from citing a seed work, no keyword match needed


class TestCitationCountBoost:
    def test_old_paper_with_citations_gets_boosted(self):
        topic = _topic()
        old_paper = _paper(published_date=_days_ago(365), cited_by_count=100)
        old_paper_no_citations = _paper(source_id="arxiv:2", published_date=_days_ago(365), cited_by_count=0)
        assert (
            score_paper(old_paper, topic, use_recency=False)
            > score_paper(old_paper_no_citations, topic, use_recency=False)
        )

    def test_new_preprint_not_penalized_for_zero_citations(self):
        topic = _topic()
        new_paper = _paper(published_date=_days_ago(1), cited_by_count=0)
        new_paper_hypothetically_cited = _paper(source_id="arxiv:2", published_date=_days_ago(1), cited_by_count=50)
        # The citation boost only applies once a paper has had time to
        # accumulate citations — a brand-new preprint shouldn't be penalized
        # for having 0, nor should an improbable 50-citations-on-day-1 boost it.
        assert (
            score_paper(new_paper, topic, use_recency=False)
            == score_paper(new_paper_hypothetically_cited, topic, use_recency=False)
        )


class TestScorePapers:
    def test_defaults_evidence_tier_to_keyword_only(self):
        topic = _topic()
        papers = [_paper()]
        score_papers(papers, topic)
        assert papers[0].evidence_tier == "keyword_only"

    def test_cites_known_work_ids_wired_through(self):
        topic = _topic(include_any=[])
        paper = _paper(title="Unrelated", abstract=None)
        score_papers([paper], topic, cites_known_work_ids={paper.source_id})
        assert paper.score > 0
