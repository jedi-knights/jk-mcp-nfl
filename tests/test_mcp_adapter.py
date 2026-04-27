"""Tests for the inbound MCP adapter — error translation, formatter wiring, server build."""

import pytest

from nfl.adapters.inbound.formatters import (
    _fmt_athlete,
    _fmt_ats_record,
    _fmt_def_points_per_100,
    _fmt_head_to_head,
    _fmt_injuries,
    _fmt_news,
    _fmt_odds,
    _fmt_ou_record,
    _fmt_qb_advanced,
    _fmt_red_zone,
    _fmt_roster,
    _fmt_schedule,
    _fmt_scoreboard,
    _fmt_situational_record,
    _fmt_standings,
    _fmt_success_rate,
    _fmt_team,
    _fmt_team_epa,
    _fmt_team_stats,
    _fmt_teams,
    _fmt_third_down,
    _fmt_weather,
)
from nfl.adapters.inbound.mcp_adapter import _safe_call, create_mcp_server
from nfl.application.service import NFLService
from nfl.domain.exceptions import NFLNotFoundError, UpstreamAPIError
from nfl.domain.models import (
    Athlete,
    ATSRecord,
    DefensiveEfficiency,
    EPAStats,
    GameOdds,
    HeadToHead,
    Match,
    MatchCompetitor,
    NewsItem,
    OURecord,
    PlayerInjury,
    QBAdvancedStats,
    RedZoneStats,
    SituationalRecord,
    Standing,
    SuccessRate,
    Team,
    TeamStats,
    ThirdDownStats,
    Weather,
)


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
    assert {
        "get_teams",
        "get_team",
        "get_scoreboard",
        "get_standings",
        "get_team_stats",
        "get_team_schedule",
        "get_head_to_head",
        "get_roster",
        "get_injuries",
        "get_athlete",
        "get_news",
        "get_team_epa",
        "get_success_rate",
        "get_third_down_rate",
        "get_red_zone_efficiency",
        "get_def_points_per_100_yards",
        "get_qb_advanced",
        "get_ats_record",
        "get_ou_record",
        "get_situational_record",
        "get_game_weather",
        "get_current_odds",
    }.issubset(tool_names)


def _kc() -> Team:
    return Team(id="12", name="Chiefs", abbreviation="KC", location="Kansas City", display_name="Kansas City Chiefs")


def _buf() -> Team:
    return Team(id="2", name="Bills", abbreviation="BUF", location="Buffalo", display_name="Buffalo Bills")


def test_fmt_team_stats_renders_known_fields() -> None:
    stats = TeamStats(
        team=_kc(),
        season=2025,
        games_played=10,
        points_per_game=27.4,
        point_differential=85,
    )
    out = _fmt_team_stats(stats)
    assert "Kansas City Chiefs" in out
    assert "2025" in out
    assert "27.4" in out
    assert "+85" in out


def test_fmt_team_stats_marks_unknown_fields() -> None:
    stats = TeamStats(team=_kc(), season=2025, games_played=10, points_per_game=27.4)
    out = _fmt_team_stats(stats)
    assert "n/a" in out  # YPG, YPP, turnover diff unavailable


def test_fmt_schedule_handles_empty() -> None:
    assert _fmt_schedule([]) == "No games found in the schedule."


def test_fmt_schedule_lists_matches() -> None:
    match = Match(
        id="1",
        date="2025-09-10",
        name="KC at BUF",
        short_name="KC @ BUF",
        status_type="post",
        status_detail="Final",
        week=1,
        competitors=[
            MatchCompetitor(team=_kc(), home_away="away", score="27", winner=True),
            MatchCompetitor(team=_buf(), home_away="home", score="24", winner=False),
        ],
    )
    out = _fmt_schedule([match])
    assert "Week 1" in out
    assert "KC 27" in out


def test_fmt_head_to_head_renders_summary_and_matches() -> None:
    match = Match(
        id="1",
        date="2025-09-10",
        name="KC at BUF",
        short_name="KC @ BUF",
        status_type="post",
        status_detail="Final",
        week=1,
        competitors=[
            MatchCompetitor(team=_kc(), home_away="away", score="27", winner=True),
            MatchCompetitor(team=_buf(), home_away="home", score="24", winner=False),
        ],
    )
    h2h = HeadToHead(team_a=_kc(), team_b=_buf(), team_a_wins=1, team_b_wins=0, ties=0, matches=[match])
    out = _fmt_head_to_head(h2h)
    assert "Kansas City Chiefs vs Buffalo Bills" in out
    assert "1-0-0" in out
    assert "KC 27" in out


def test_fmt_head_to_head_no_matches() -> None:
    h2h = HeadToHead(team_a=_kc(), team_b=_buf(), team_a_wins=0, team_b_wins=0, ties=0)
    out = _fmt_head_to_head(h2h)
    assert "No recent matchups" in out


def test_fmt_roster_empty() -> None:
    assert _fmt_roster([]) == "No roster entries found."


def test_fmt_roster_lists_athletes() -> None:
    roster = [
        Athlete(id="1", full_name="Patrick Mahomes", position="QB", jersey="15"),
        Athlete(id="2", full_name="Travis Kelce", position="TE", jersey="87"),
    ]
    out = _fmt_roster(roster)
    assert "Patrick Mahomes" in out
    assert "QB" in out
    assert "#15" in out


def test_fmt_injuries_empty() -> None:
    assert _fmt_injuries([]) == "No injuries reported."


def test_fmt_injuries_lists_entries() -> None:
    injuries = [
        PlayerInjury(player_name="Travis Kelce", position="TE", status="Questionable", team=_kc(), description="knee"),
        PlayerInjury(player_name="Stefon Diggs", position="WR", status="Out", team=_buf()),
    ]
    out = _fmt_injuries(injuries)
    assert "Travis Kelce" in out
    assert "Questionable" in out
    assert "knee" in out


def test_fmt_athlete_renders_profile() -> None:
    athlete = Athlete(
        id="3139477",
        full_name="Patrick Mahomes",
        position="QB",
        team=_kc(),
        jersey="15",
        height="6'3\"",
        weight="230 lbs",
        age=30,
    )
    out = _fmt_athlete(athlete)
    assert "Patrick Mahomes" in out
    assert "QB" in out
    assert "Kansas City Chiefs" in out
    assert "15" in out


def test_fmt_news_empty() -> None:
    assert _fmt_news([]) == "No news available."


def test_fmt_news_lists_articles() -> None:
    news = [
        NewsItem(
            headline="Trade rumors",
            description="A description.",
            published="2026-01-05T18:00:00Z",
            url="https://espn.com/x",
        ),
    ]
    out = _fmt_news(news)
    assert "Trade rumors" in out
    assert "https://espn.com/x" in out


async def test_safe_call_translates_runtime_error() -> None:
    result = await _safe_call(_async_raise(RuntimeError("nflverse missing")), str)
    assert result.startswith("Unavailable:")


def test_fmt_team_epa_renders_signed_values() -> None:
    epa = EPAStats(
        team=_kc(),
        season=2025,
        side="offense",
        epa_per_play=0.123,
        pass_epa_per_play=0.21,
        rush_epa_per_play=-0.02,
        success_rate=0.47,
    )
    out = _fmt_team_epa(epa)
    assert "+0.123" in out
    assert "0.470" in out
    assert "offense" in out


def test_fmt_success_rate_includes_play_counts() -> None:
    sr = SuccessRate(
        team=_kc(), season=2025, rate_offense=0.47, rate_defense=0.39, plays_offense=1100, plays_defense=1050
    )
    out = _fmt_success_rate(sr)
    assert "0.470" in out
    assert "1100 plays" in out


def test_fmt_third_down_renders_both_sides() -> None:
    td = ThirdDownStats(
        team=_kc(),
        season=2025,
        attempts_offense=130,
        conversions_offense=55,
        rate_offense=0.42,
        attempts_defense=125,
        conversions_defense_allowed=48,
        rate_defense=0.38,
    )
    out = _fmt_third_down(td)
    assert "55/130" in out
    assert "48/125" in out


def test_fmt_red_zone_renders_both_sides() -> None:
    rz = RedZoneStats(
        team=_kc(),
        season=2025,
        trips_offense=40,
        touchdowns_offense=26,
        td_rate_offense=0.65,
        trips_defense=35,
        touchdowns_defense_allowed=18,
        td_rate_defense=0.514,
    )
    out = _fmt_red_zone(rz)
    assert "26/40" in out
    assert "18/35" in out


def test_fmt_ats_record_includes_situation_label() -> None:
    record = ATSRecord(team=_kc(), season=2025, wins=4, losses=2, pushes=1, situation="home")
    out = _fmt_ats_record(record)
    assert "ATS (home)" in out
    assert "4-2-1" in out


def test_fmt_ats_record_overall_when_no_situation() -> None:
    record = ATSRecord(team=_kc(), season=2025, wins=8, losses=4, pushes=1)
    out = _fmt_ats_record(record)
    assert "ATS (overall)" in out


def test_fmt_odds_empty() -> None:
    assert _fmt_odds([]) == "No live odds available."


def test_fmt_odds_renders_each_game() -> None:
    odds = [
        GameOdds(
            game_id="abc",
            book="DraftKings",
            timestamp="2026-01-05T18:00:00Z",
            spread=-3.5,
            total=48.5,
            moneyline_home=-180,
            moneyline_away=160,
        ),
    ]
    out = _fmt_odds(odds)
    assert "DraftKings" in out
    assert "-3.5" in out
    assert "48.5" in out
    assert "+160" in out


def test_fmt_weather_indoor_short_circuits() -> None:
    out = _fmt_weather(Weather(game_id="DET-20251005", is_indoor=True))
    assert "indoor (dome stadium)" in out


def test_fmt_weather_outdoor_renders_metrics() -> None:
    weather = Weather(
        game_id="KC-20250915",
        is_indoor=False,
        temperature_f=42.5,
        wind_mph=14.0,
        precipitation_chance=0.6,
        condition="Rain",
    )
    out = _fmt_weather(weather)
    assert "42°F" in out  # rounded to 0 decimals
    assert "14 mph" in out
    assert "Rain" in out


def test_fmt_situational_record_renders_su_and_ats_lines() -> None:
    record = SituationalRecord(
        team=_kc(),
        season=2025,
        situation="dome",
        su_wins=4,
        su_losses=1,
        su_ties=0,
        ats_wins=3,
        ats_losses=1,
        ats_pushes=1,
    )
    out = _fmt_situational_record(record)
    assert "dome" in out
    assert "SU:   4-1-0" in out
    assert "ATS:  3-1-1" in out


def test_fmt_ou_record_renders_overs_unders_pushes() -> None:
    record = OURecord(team=_kc(), season=2025, overs=6, unders=3, pushes=1)
    out = _fmt_ou_record(record)
    assert "6-3-1" in out


def test_fmt_qb_advanced_renders_full_line() -> None:
    qb = QBAdvancedStats(
        athlete_id="3139477",
        name="Patrick Mahomes",
        season=2025,
        completion_percent=0.671,
        yards_per_attempt=8.1,
        touchdowns=32,
        interceptions=8,
        td_int_ratio=4.0,
        passer_rating=104.5,
        cpoe=3.2,
        epa_per_play=0.18,
    )
    out = _fmt_qb_advanced(qb)
    assert "Patrick Mahomes" in out
    assert "104.5" in out
    assert "+3.20" in out
    assert "32 / 8" in out


def test_fmt_def_points_per_100_includes_rating_legend() -> None:
    de = DefensiveEfficiency(
        team=_kc(), season=2025, yards_allowed=4200, points_allowed=320, points_per_100_yards=7.62, rating="poor"
    )
    out = _fmt_def_points_per_100(de)
    assert "7.620" in out
    assert "poor" in out
    assert "good <6.0" in out
