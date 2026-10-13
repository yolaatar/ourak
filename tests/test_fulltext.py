"""Tests for full-text evidence classification (app/fulltext.py).

verify_topic_usage is the core judgment call this session made by hand,
repeatedly, reading quoted sentences from citing papers: does the full text
show the paper actually *used* the topic's subject, or just mention it in
passing? These fixtures mirror the real distinction found in that session
(e.g. "We used the Spine Generic Public Database..." vs. a review paper's
"...the spine generic protocol was recently released...").
"""

from unittest.mock import patch

from app.models import Topic
from app.fulltext import apply_evidence_pass, verify_topic_usage
from app.models import Paper


def _topic(**overrides) -> Topic:
    defaults = dict(
        name="test-topic",
        include_any=["spine generic"],
        include_all=[],
        exclude=[],
    )
    defaults.update(overrides)
    return Topic(**defaults)


class TestVerifyTopicUsage:
    def test_no_text_is_keyword_only(self):
        tier, snippet = verify_topic_usage(None, _topic())
        assert tier == "keyword_only"
        assert snippet is None

    def test_no_match_is_keyword_only(self):
        tier, snippet = verify_topic_usage("this text is about something else entirely", _topic())
        assert tier == "keyword_only"
        assert snippet is None

    def test_match_near_usage_verb_is_confirmed(self):
        text = (
            "Materials and methods. We used data from the spine generic "
            "multi-subject dataset for model development."
        )
        tier, snippet = verify_topic_usage(text, _topic())
        assert tier == "confirmed"
        assert "spine generic" in snippet.lower()

    def test_match_without_usage_verb_is_mentioned(self):
        text = (
            "Discussion. The field's most complete work, so-called spine "
            "generic, involved forty-two centres worldwide and multiple vendors."
        )
        tier, snippet = verify_topic_usage(text, _topic())
        assert tier == "mentioned"
        assert "spine generic" in snippet.lower()


class TestApplyEvidencePass:
    def test_skips_papers_outside_the_band(self):
        low_score_paper = Paper(source="arxiv", source_id="a:1", title="x", doi="10.1/x", score=10.0)
        high_score_paper = Paper(source="arxiv", source_id="a:2", title="y", doi="10.1/y", score=90.0)
        with patch("app.fulltext.fetch_fulltext") as mock_fetch:
            apply_evidence_pass(
                [low_score_paper, high_score_paper], _topic(),
                evidence_band=(30.0, 65.0), max_checks=5,
            )
            mock_fetch.assert_not_called()

    def test_skips_papers_without_doi(self):
        paper = Paper(source="arxiv", source_id="a:1", title="x", doi=None, score=50.0)
        with patch("app.fulltext.fetch_fulltext") as mock_fetch:
            apply_evidence_pass([paper], _topic(), evidence_band=(30.0, 65.0), max_checks=5)
            mock_fetch.assert_not_called()

    def test_confirmed_result_bumps_score(self):
        paper = Paper(source="arxiv", source_id="a:1", title="x", doi="10.1/x", score=50.0)
        with patch("app.fulltext.fetch_fulltext", return_value="we used the spine generic dataset for this study"):
            apply_evidence_pass([paper], _topic(), evidence_band=(30.0, 65.0), max_checks=5)
        assert paper.evidence_tier == "confirmed"
        assert paper.score > 50.0

    def test_respects_max_checks(self):
        papers = [
            Paper(source="arxiv", source_id=f"a:{i}", title="x", doi=f"10.1/{i}", score=50.0)
            for i in range(10)
        ]
        with patch("app.fulltext.fetch_fulltext", return_value=None) as mock_fetch:
            apply_evidence_pass(papers, _topic(), evidence_band=(30.0, 65.0), max_checks=3)
            assert mock_fetch.call_count == 3
