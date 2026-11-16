"""Tests for the NeuroPoly team page scraper (current vs. alumni)."""

from unittest.mock import MagicMock, patch

from app.sources import team_roster

_FIXTURE_HTML = """
<h2>Faculty<a class="headerlink" href="#faculty">#</a></h2>
<ul class="simple">
<li><p><a href="faculty/jane-lab.html"><span>Jane Lab</span></a>
<a href="mailto:x"><i class="fa fa-envelope"></i></a></p></li>
</ul>
<h2>PhD Students<a class="headerlink" href="#phd-students">#</a></h2>
<ul class="simple">
<li><p>Bob Lab
<a href="mailto:x"><i class="fa fa-envelope"></i></a></p></li>
</ul>
<h2>Alumni<a class="headerlink" href="#alumni">#</a></h2>
<ul class="simple">
<li><p>Aldo Zaimi
<a href="https://github.com/aldozaimi"><i class="fab fa-github"></i></a></p></li>
<li><p>Someone Else</p></li>
</ul>
"""


def test_parse_team_html_splits_current_and_alumni():
    current, alumni = team_roster._parse_team_html(_FIXTURE_HTML)
    assert current == {"jane lab", "bob lab"}
    assert alumni == {"aldo zaimi", "someone else"}


def test_parse_team_html_ignores_icon_link_noise():
    # icon-only <a> tags (envelope/github/etc.) must not leak into the name text
    current, _ = team_roster._parse_team_html(_FIXTURE_HTML)
    assert "jane lab" in current
    assert not any("fa-envelope" in name for name in current)


@patch("app.sources.team_roster.requests.get")
def test_fetch_team_roster_raises_on_http_error(mock_get):
    mock_get.return_value = MagicMock(raise_for_status=MagicMock(side_effect=RuntimeError("boom")))
    try:
        team_roster.fetch_team_roster()
        assert False, "expected an exception"
    except RuntimeError:
        pass
