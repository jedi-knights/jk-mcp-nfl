"""Tests for the domain dataclasses — minimal, mostly construction & defaults."""

from nfl.domain.exceptions import NFLError, NFLNotFoundError, UpstreamAPIError
from nfl.domain.models import Match, MatchCompetitor, Standing, Team


def test_team_defaults_optional_fields_to_none() -> None:
    team = Team(id="12", name="Chiefs", abbreviation="KC", location="Kansas City", display_name="Kansas City Chiefs")
    assert team.conference is None
    assert team.division is None
    assert team.logo_url is None


def test_match_defaults_competitors_to_empty_list() -> None:
    match = Match(
        id="1", date="2026-01-05", name="A vs B", short_name="A @ B", status_type="pre", status_detail="Sched"
    )
    assert match.competitors == []
    assert match.week is None


def test_standing_carries_record_and_diff() -> None:
    team = Team(id="1", name="x", abbreviation="x", location="x", display_name="x")
    standing = Standing(
        team=team,
        wins=10,
        losses=6,
        ties=1,
        win_percent=0.617,
        points_for=420,
        points_against=350,
        point_differential=70,
    )
    assert standing.point_differential == 70
    assert standing.win_percent == 0.617


def test_match_competitor_optional_fields() -> None:
    team = Team(id="1", name="x", abbreviation="x", location="x", display_name="x")
    competitor = MatchCompetitor(team=team, home_away="home")
    assert competitor.score is None
    assert competitor.winner is None


def test_exception_hierarchy() -> None:
    assert issubclass(NFLNotFoundError, NFLError)
    assert issubclass(UpstreamAPIError, NFLError)
