"""Tests for the OpenAlex lab fetcher."""

from unittest.mock import MagicMock, patch

from app.models import LabAuthor, LabConfig
from app.sources import openalex

CFG = LabConfig(
    lab_name="TestLab",
    affiliations=["NeuroPoly"],
    authors=[
        LabAuthor(name="Jane Lab", orcid="https://orcid.org/0000-0001-0000-0001"),
        LabAuthor(name="Bob Lab", openalex_ids=["https://openalex.org/A1", "A2"]),
    ],
)


def _work(work_id, title, *, authors=(), refs=(), doi=None):
    return {
        "id": f"https://openalex.org/{work_id}",
        "doi": f"https://doi.org/{doi}" if doi else None,
        "title": title,
        "publication_date": "2026-09-10",
        "authorships": [
            {
                "author": {"id": f"https://openalex.org/{aid}", "display_name": name, "orcid": orcid},
                "raw_affiliation_strings": [affil],
            }
            for aid, name, orcid, affil in authors
        ],
        "primary_location": {"source": {"display_name": "NeuroImage"}, "landing_page_url": "https://x.org"},
        "abstract_inverted_index": {"Axons": [0], "are": [1], "segmented": [2]},
        "referenced_works": [f"https://openalex.org/{r}" for r in refs],
    }


def _page(results, next_cursor=None):
    resp = MagicMock()
    resp.json.return_value = {"meta": {"next_cursor": next_cursor}, "results": results}
    return resp


def test_lab_filters_one_per_match_type():
    assert openalex._lab_filters(CFG) == [
        "author.orcid:0000-0001-0000-0001",
        "authorships.author.id:A1|A2",
        "raw_affiliation_strings.search:NeuroPoly",
    ]


def test_abstract_from_inverted_index():
    assert openalex._abstract_from_index({"b": [1], "a": [0, 2]}) == "a b a"
    assert openalex._abstract_from_index(None) is None


def test_parse_work_fields():
    paper = openalex._parse_work(_work("W9", "A title", doi="10.1/abc"), "authored")
    assert paper.source_id == "openalex:W9"
    assert paper.doi == "10.1/abc"
    assert paper.url == "https://doi.org/10.1/abc"
    assert paper.journal == "NeuroImage"
    assert paper.abstract == "Axons are segmented"


def test_parse_work_url_fallback_without_doi():
    paper = openalex._parse_work(_work("W9", "A title"), "citing")
    assert paper.url == "https://x.org"


@patch("app.sources.openalex.time.sleep")
@patch("app.sources.openalex.requests.get")
def test_get_all_follows_cursor(mock_get, _sleep):
    mock_get.side_effect = [_page([{"id": "W1"}], "next"), _page([{"id": "W2"}])]
    results = openalex._get_all("author.orcid:x", "id")
    assert [r["id"] for r in results] == ["W1", "W2"]
    assert mock_get.call_args_list[1].kwargs["params"]["cursor"] == "next"


@patch("app.sources.openalex._get_all")
def test_fetch_lab_papers_matches_lab_authors(mock_get_all):
    work = _work("W1", "Lab paper", authors=[
        ("A9", "Jane L.", "https://orcid.org/0000-0001-0000-0001", "Elsewhere"),
        ("A2", "Bob L.", None, "Elsewhere"),
        ("A5", "New Student", None, "NeuroPoly Lab, Polytechnique Montreal"),
        ("A7", "Outsider", None, "Some other university"),
    ])
    mock_get_all.side_effect = [[work], [work], [work]]  # same work from all three filters
    papers = openalex.fetch_lab_papers(CFG, days_back=30)
    assert len(papers) == 1
    assert papers[0].kind == "authored"
    assert papers[0].lab_authors == ["Jane Lab", "Bob Lab", "New Student"]
    filter_str = mock_get_all.call_args_list[0].args[0]
    assert "from_publication_date:" in filter_str
    assert "type:article|preprint" in filter_str


def test_match_lab_authors_falls_back_to_affiliation():
    work = _work("W1", "Lab paper", authors=[
        ("A5", "New Student", None, "NeuroPoly Lab, Polytechnique Montreal"),
        ("A7", "Outsider", None, "Some other university"),
    ])
    assert openalex._match_lab_authors(work, CFG) == ["New Student"]


def test_match_lab_authors_ignores_lumped_affiliations():
    lumped = "From Temple University (Z.S.A.) and NeuroPoly Lab, Polytechnique (J.C.-A.) " * 5
    work = _work("W1", "Lab paper", authors=[
        ("A5", "Someone", None, lumped),
        ("A7", "Someone Else", None, lumped),
    ])
    assert openalex._match_lab_authors(work, CFG) == []


def test_match_lab_authors_by_name_when_profile_lacks_orcid():
    work = _work("W1", "Lab paper", authors=[
        ("A99", "jane-lab", None, "Elsewhere"),  # stray profile, no ORCID
        ("A7", "Outsider", None, "Elsewhere"),
    ])
    assert openalex._match_lab_authors(work, CFG) == ["Jane Lab"]


def test_norm_name_folds_accents_and_hyphens():
    assert openalex._norm_name("Jan Valošek") == openalex._norm_name("jan valosek")
    assert openalex._norm_name("Pierre‐Louis Benveniste") == "pierre louis benveniste"


def _lab_work(title, authors=None, published_date=None):
    return {"title": title, "authors": authors or [], "published_date": published_date}


@patch("app.sources.openalex._get_all")
def test_fetch_citing_skips_self_citations_and_collects_cited_titles(mock_get_all):
    lab_works = {"W1": _lab_work("Lab paper one"), "W2": _lab_work("Lab paper two")}
    mock_get_all.return_value = [
        _work("W50", "External citing paper", refs=["W1", "W2", "W999"]),
        _work("W2", "Lab paper two", refs=["W1"]),  # lab citing itself
    ]
    papers = openalex.fetch_citing_papers(lab_works, days_back=30)
    assert [p.source_id for p in papers] == ["openalex:W50"]
    assert papers[0].kind == "citing"
    assert papers[0].cited_lab_works == [lab_works["W1"], lab_works["W2"]]
    assert mock_get_all.call_args.args[0].startswith("cites:W1|W2,type:article|")


@patch("app.sources.openalex._get_all")
def test_fetch_citing_merges_across_chunks(mock_get_all):
    lab_works = {f"W{i}": _lab_work(f"Lab {i}") for i in range(openalex._OR_CHUNK + 1)}
    first_chunk_ref, last_ref = sorted(lab_works)[0], sorted(lab_works)[-1]
    mock_get_all.side_effect = [
        [_work("W500", "Citing", refs=[first_chunk_ref])],
        [_work("W500", "Citing", refs=[last_ref])],
    ]
    papers = openalex.fetch_citing_papers(lab_works, days_back=30)
    assert len(papers) == 1
    assert papers[0].cited_lab_works == [lab_works[first_chunk_ref], lab_works[last_ref]]


# --- Lab-led ranking ---


def test_is_first_author_from_lab_true_when_lab_member_leads():
    work = _work("W1", "Lab paper", authors=[
        ("A1", "Jane Lab", "https://orcid.org/0000-0001-0000-0001", "NeuroPoly"),
        ("A7", "Outsider", None, "Elsewhere"),
    ])
    assert openalex._is_first_author_from_lab(work, CFG) is True


def test_is_first_author_from_lab_false_when_lab_member_is_last():
    # e.g. the PI as senior/corresponding author on an external collaboration —
    # a lab member is present, but didn't drive the work
    work = _work("W1", "External paper", authors=[
        ("A7", "Outsider", None, "Elsewhere"),
        ("A8", "Someone Else", None, "Elsewhere"),
        ("A1", "Jane Lab", "https://orcid.org/0000-0001-0000-0001", "NeuroPoly"),
    ])
    assert openalex._is_first_author_from_lab(work, CFG) is False


def test_is_first_author_from_lab_false_with_no_authors():
    assert openalex._is_first_author_from_lab(_work("W1", "No authors"), CFG) is False


# --- Alumni exclusion ---


def test_match_lab_authors_excludes_alumni():
    work = _work("W1", "Post-departure paper", authors=[
        ("A1", "Jane Lab", "https://orcid.org/0000-0001-0000-0001", "NeuroPoly"),
    ])
    assert openalex._match_lab_authors(work, CFG, alumni=frozenset({"jane lab"})) == []


def test_is_first_author_false_when_only_alumnus_matches():
    # e.g. Jane Lab's new paper at her new institution, still tagged "NeuroPoly"
    work = _work("W1", "New unrelated paper", authors=[
        ("A1", "Jane Lab", "https://orcid.org/0000-0001-0000-0001", "NeuroPoly"),
        ("A7", "Outsider", None, "Elsewhere"),
    ])
    assert openalex._is_first_author_from_lab(work, CFG, alumni=frozenset({"jane lab"})) is False


def test_is_first_author_true_when_current_member_also_coauthored():
    # AxonDeepSeg-style: Jane Lab (now alumna) led it, but Bob Lab (still current,
    # e.g. the PI) co-authored — this is real historical lab output, keep it ranked
    work = _work("W1", "AxonDeepSeg-like paper", authors=[
        ("A1", "Jane Lab", "https://orcid.org/0000-0001-0000-0001", "NeuroPoly"),
        ("A2", "Bob Lab", None, "NeuroPoly"),
    ])
    assert openalex._is_first_author_from_lab(work, CFG, alumni=frozenset({"jane lab"})) is True


@patch("app.sources.openalex._get_all")
def test_fetch_lab_papers_drops_alumni_only_matches(mock_get_all):
    mock_get_all.return_value = [
        _work("W1", "Alumna's new paper", authors=[
            ("A1", "Jane Lab", "https://orcid.org/0000-0001-0000-0001", "NeuroPoly"),
        ]),
    ]
    papers = openalex.fetch_lab_papers(CFG, days_back=30, alumni=frozenset({"jane lab"}))
    assert papers == []


@patch("app.sources.openalex._get_all")
def test_fetch_lab_works_reports_current_lab_coauthors(mock_get_all):
    # Jane Lab (alumna) leads it, Bob Lab (current) co-authors — not lab-led,
    # but Bob should still be surfaced as the current-lab connection
    mock_get_all.return_value = [
        _work("W1", "AxonDeepSeg-like paper", authors=[
            ("A1", "Jane Lab", "https://orcid.org/0000-0001-0000-0001", "NeuroPoly"),
            ("A2", "Bob Lab", None, "NeuroPoly"),
        ]),
    ]
    works = openalex.fetch_lab_works(CFG, alumni=frozenset({"jane lab"}))
    assert works["W1"]["is_first_author"] is True  # Bob's presence keeps it lab-led
    assert works["W1"]["lab_coauthors"] == ["Bob Lab"]


@patch("app.sources.openalex._get_all")
def test_fetch_lab_works_coauthor_on_not_lab_led_paper(mock_get_all):
    # A total outsider leads a big consortium paper; Bob Lab is buried mid-list —
    # not lab-led, but Bob is still the current-lab connection worth surfacing
    mock_get_all.return_value = [
        _work("W1", "Big Consortium Paper", authors=[
            ("A7", "Outsider", None, "Elsewhere"),
            ("A2", "Bob Lab", None, "NeuroPoly"),
            ("A8", "Someone Else", None, "Elsewhere"),
        ]),
    ]
    works = openalex.fetch_lab_works(CFG)
    assert works["W1"]["is_first_author"] is False
    assert works["W1"]["lab_coauthors"] == ["Bob Lab"]
