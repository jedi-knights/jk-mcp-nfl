"""Tests for the inbound MCP adapter — error translation, formatter wiring, server build."""

import pytest

from nfl.adapters.inbound.formatters import _fmt_scoreboard, _fmt_standings, _fmt_team, _fmt_teams
from nfl.adapters.inbound.mcp_adapter import _safe_call, create_mcp_server
from nfl.application.service import NFLService
from nfl.domain.exceptions import NFLNotFoundError, UpstreamAPIError
from nfl.domain.models import Match, MatchCompetitor, Standing, Team


async def _async_value(value):
    return value


async def _async_raise(exc):
    raise exc


async def test_safe_call_returns_formatted_value() -> None:
    result = await _safe_call(_async_value("hello"), str.upper)
    assert result == "HELLO"


async def test_safe_call_translates_not_found() -> None:
    result = await _safe_call(_async_raise(NFLNotFoundError("team 999")), str)
    assert result.startswith("Not found:")


async def test_safe_call_translates_upstream_error() -> None:
    result = await _safe_call(_async_raise(UpstreamAPIError("500")), str)
    assert result.startswith("Upstream error:")


async def test_safe_call_translates_value_error() -> None:
    result = await _safe_call(_async_raise(ValueError("nope")), str)
    assert result.startswith("Invalid request:")


def test_fmt_teams_empty() -> None:
    assert _fmt_teams([]) == "No teams found."


def test_fmt_teams_lists_each() -> None:
    teams = [Team(id="12", name="Chiefs", abbreviation="KC", location="KC", display_name="Kansas City Chiefs")]
    out = _fmt_teams(teams)
    assert "Kansas City Chiefs" in out
    assert "KC" in out


def test_fmt_team_includes_division_when_present() -> None:
    team = Team(
        id="12",
        name="Chiefs",
        abbreviation="KC",
        location="Kansas City",
        display_name="Kansas City Chiefs",
        conference="AFC",
        division="West",
    )
    assert "AFC West" in _fmt_team(team)


def test_fmt_scoreboard_handles_empty() -> None:
    assert _fmt_scoreboard([]) == "No NFL games found for that period."


def test_fmt_scoreboard_renders_match() -> None:
    team_a = Team(id="12", name="Chiefs", abbreviation="KC", location="x", display_name="Chiefs")
    team_b = Team(id="2", name="Bills", abbreviation="BUF", location="x", display_name="Bills")
    match = Match(
        id="1",
        date="2026-01-05",
        name="KC at BUF",
        short_name="KC @ BUF",
        status_type="post",
        status_detail="Final",
        week=18,
        competitors=[
            MatchCompetitor(team=team_a, home_away="away", score="27", winner=True),
            MatchCompetitor(team=team_b, home_away="home", score="24", winner=False),
        ],
    )
    out = _fmt_scoreboard([match])
    assert "Week 18" in out
    assert "KC 27" in out
    assert "BUF 24" in out


def test_fmt_standings_handles_empty() -> None:
    assert _fmt_standings([]) == "No standings available."


def test_fmt_standings_renders_row() -> None:
    team = Team(id="2", name="Bills", abbreviation="BUF", location="Buffalo", display_name="Buffalo Bills")
    standing = Standing(
        team=team,
        wins=13,
        losses=4,
        ties=0,
        win_percent=0.765,
        points_for=480,
        points_against=320,
        point_differential=160,
    )
    out = _fmt_standings([standing])
    assert "Buffalo Bills" in out
    assert "+160" in out


@pytest.fixture
def service(stub_repo) -> NFLService:
    return NFLService(repo=stub_repo)


def test_create_mcp_server_registers_expected_tools(service) -> None:
    mcp = create_mcp_server(service)
    # FastMCP exposes registered tools via list_tools(); we just verify creation succeeds
    # and the tool registry is non-empty by checking the underlying _tool_manager.
    tool_names = set(mcp._tool_manager._tools.keys())
    assert {"get_teams", "get_team", "get_scoreboard", "get_standings"}.issubset(tool_names)
