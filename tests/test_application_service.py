"""Tests for the application service — input validation and port delegation."""

import pytest

from nfl.application.service import NFLService
from nfl.domain.models import (
    Athlete,
    ATSRecord,
    DefensiveEfficiency,
    EPAStats,
    GameOdds,
    Match,
    MatchCompetitor,
    NewsItem,
    OURecord,
    PlayerInjury,
    QBAdvancedStats,
    RedZoneStats,
    SituationalRecord,
    SuccessRate,
    Team,
    TeamStats,
    ThirdDownStats,
    Weather,
)


def _team(team_id: str = "12", abbr: str = "KC") -> Team:
    return Team(id=team_id, name=abbr, abbreviation=abbr, location=abbr, display_name=abbr)


def _match(
    match_id: str, date: str, away: Team, home: Team, away_score: str, home_score: str, away_winner: bool
) -> Match:
    return Match(
        id=match_id,
        date=date,
        name=f"{away.abbreviation} at {home.abbreviation}",
        short_name=f"{away.abbreviation} @ {home.abbreviation}",
        status_type="post",
        status_detail="Final",
        week=1,
        competitors=[
            MatchCompetitor(team=away, home_away="away", score=away_score, winner=away_winner),
            MatchCompetitor(team=home, home_away="home", score=home_score, winner=not away_winner),
        ],
    )


async def test_get_teams_delegates(stub_repo) -> None:
    stub_repo.teams = [_team()]
    service = NFLService(repo=stub_repo)
    result = await service.get_teams()
    assert result == [_team()]
    assert stub_repo.calls == [("get_teams", {})]


async def test_get_team_strips_and_passes_id(stub_repo) -> None:
    stub_repo.team_by_id["12"] = _team()
    service = NFLService(repo=stub_repo)
    await service.get_team("  12  ")
    assert stub_repo.calls == [("get_team", {"team_id": "12"})]


@pytest.mark.parametrize("bad", ["", "   "])
async def test_get_team_rejects_blank(stub_repo, bad: str) -> None:
    service = NFLService(repo=stub_repo)
    with pytest.raises(ValueError):
        await service.get_team(bad)


async def test_get_scoreboard_rejects_malformed_date(stub_repo) -> None:
    service = NFLService(repo=stub_repo)
    with pytest.raises(ValueError):
        await service.get_scoreboard("2026-01-05")


async def test_get_scoreboard_normalizes_date(stub_repo) -> None:
    service = NFLService(repo=stub_repo)
    await service.get_scoreboard("  20260105  ")
    assert stub_repo.calls == [("get_scoreboard", {"date": "20260105"})]


async def test_get_scoreboard_passes_through_none(stub_repo) -> None:
    service = NFLService(repo=stub_repo)
    await service.get_scoreboard()
    assert stub_repo.calls == [("get_scoreboard", {"date": None})]


async def test_get_standings_delegates(stub_repo) -> None:
    service = NFLService(repo=stub_repo)
    await service.get_standings()
    assert stub_repo.calls == [("get_standings", {})]


async def test_get_team_stats_delegates_with_season(stub_repo) -> None:
    stub_repo.team_stats_by_id["12"] = TeamStats(team=_team(), season=2025, games_played=10)
    service = NFLService(repo=stub_repo)
    await service.get_team_stats("  12  ", season=2025)
    assert stub_repo.calls == [("get_team_stats", {"team_id": "12", "season": 2025})]


async def test_get_team_stats_rejects_blank_id(stub_repo) -> None:
    service = NFLService(repo=stub_repo)
    with pytest.raises(ValueError):
        await service.get_team_stats("")


async def test_get_team_stats_rejects_unreasonable_season(stub_repo) -> None:
    service = NFLService(repo=stub_repo)
    with pytest.raises(ValueError):
        await service.get_team_stats("12", season=1900)


async def test_get_team_schedule_delegates(stub_repo) -> None:
    service = NFLService(repo=stub_repo)
    await service.get_team_schedule("12", season=2025)
    assert stub_repo.calls == [("get_team_schedule", {"team_id": "12", "season": 2025})]


async def test_get_team_schedule_rejects_blank_id(stub_repo) -> None:
    service = NFLService(repo=stub_repo)
    with pytest.raises(ValueError):
        await service.get_team_schedule("")


async def test_get_head_to_head_rejects_same_team(stub_repo) -> None:
    service = NFLService(repo=stub_repo)
    with pytest.raises(ValueError):
        await service.get_head_to_head("12", "12")


async def test_get_head_to_head_rejects_non_positive_last_n(stub_repo) -> None:
    service = NFLService(repo=stub_repo)
    with pytest.raises(ValueError):
        await service.get_head_to_head("1", "2", last_n=0)


async def test_get_head_to_head_filters_to_opponent_and_counts(stub_repo) -> None:
    a, b, c = _team("1", "AAA"), _team("2", "BBB"), _team("3", "CCC")
    stub_repo.schedule_by_team["1"] = [
        _match("e1", "2025-09-10", away=a, home=b, away_score="20", home_score="17", away_winner=True),
        _match(
            "e2", "2025-10-15", away=c, home=a, away_score="14", home_score="21", away_winner=False
        ),  # vs C, irrelevant
        _match("e3", "2025-12-20", away=b, home=a, away_score="30", home_score="27", away_winner=True),
    ]
    service = NFLService(repo=stub_repo)
    h2h = await service.get_head_to_head("1", "2", last_n=10)
    assert h2h.team_a.id == "1"
    assert h2h.team_b.id == "2"
    assert len(h2h.matches) == 2  # only the two A-vs-B games
    assert h2h.team_a_wins == 1
    assert h2h.team_b_wins == 1
    assert h2h.ties == 0


async def test_get_head_to_head_returns_most_recent_first(stub_repo) -> None:
    a, b = _team("1", "AAA"), _team("2", "BBB")
    stub_repo.schedule_by_team["1"] = [
        _match("e1", "2025-09-10", away=a, home=b, away_score="20", home_score="17", away_winner=True),
        _match("e2", "2025-12-20", away=b, home=a, away_score="30", home_score="27", away_winner=True),
    ]
    service = NFLService(repo=stub_repo)
    h2h = await service.get_head_to_head("1", "2", last_n=10)
    assert h2h.matches[0].id == "e2"  # most recent first
    assert h2h.matches[1].id == "e1"


async def test_get_head_to_head_caps_at_last_n(stub_repo) -> None:
    a, b = _team("1", "AAA"), _team("2", "BBB")
    stub_repo.schedule_by_team["1"] = [
        _match(f"e{i}", f"2025-09-{i:02d}", away=a, home=b, away_score="20", home_score="17", away_winner=True)
        for i in range(1, 8)
    ]
    service = NFLService(repo=stub_repo)
    h2h = await service.get_head_to_head("1", "2", last_n=3)
    assert len(h2h.matches) == 3


async def test_get_roster_delegates_with_stripped_id(stub_repo) -> None:
    stub_repo.roster_by_team["12"] = [Athlete(id="1", full_name="Patrick Mahomes", position="QB")]
    service = NFLService(repo=stub_repo)
    await service.get_roster("  12  ")
    assert stub_repo.calls == [("get_roster", {"team_id": "12"})]


async def test_get_roster_rejects_blank_id(stub_repo) -> None:
    service = NFLService(repo=stub_repo)
    with pytest.raises(ValueError):
        await service.get_roster("")


async def test_get_injuries_with_team_strips_id(stub_repo) -> None:
    stub_repo.injuries_by_team["12"] = [PlayerInjury(player_name="X", position="WR", status="Out")]
    service = NFLService(repo=stub_repo)
    await service.get_injuries("  12  ")
    assert stub_repo.calls == [("get_injuries", {"team_id": "12"})]


async def test_get_injuries_without_team_passes_none(stub_repo) -> None:
    service = NFLService(repo=stub_repo)
    await service.get_injuries()
    assert stub_repo.calls == [("get_injuries", {"team_id": None})]


async def test_get_athlete_strips_and_passes_id(stub_repo) -> None:
    stub_repo.athlete_by_id["3139477"] = Athlete(id="3139477", full_name="Patrick Mahomes", position="QB")
    service = NFLService(repo=stub_repo)
    await service.get_athlete("  3139477  ")
    assert stub_repo.calls == [("get_athlete", {"athlete_id": "3139477"})]


async def test_get_athlete_rejects_blank_id(stub_repo) -> None:
    service = NFLService(repo=stub_repo)
    with pytest.raises(ValueError):
        await service.get_athlete("")


async def test_get_news_default_limit_and_no_team(stub_repo) -> None:
    service = NFLService(repo=stub_repo)
    await service.get_news()
    assert stub_repo.calls == [("get_news", {"team_id": None, "limit": 10})]


async def test_get_news_with_team_and_limit(stub_repo) -> None:
    stub_repo.news_by_team["12"] = [NewsItem(headline="x", description="x", published="2025-09-01T00:00:00Z")]
    service = NFLService(repo=stub_repo)
    await service.get_news("12", limit=3)
    assert stub_repo.calls == [("get_news", {"team_id": "12", "limit": 3})]


async def test_get_news_rejects_non_positive_limit(stub_repo) -> None:
    service = NFLService(repo=stub_repo)
    with pytest.raises(ValueError):
        await service.get_news(limit=0)


async def test_get_news_caps_excessive_limit(stub_repo) -> None:
    service = NFLService(repo=stub_repo)
    await service.get_news(limit=9999)
    assert stub_repo.calls[0][1]["limit"] == 50  # capped to MAX_NEWS_LIMIT


# ---------- nflverse-backed tools (NFLDataPort) ----------


def _kc_team() -> Team:
    return Team(id="12", name="Chiefs", abbreviation="KC", location="Kansas City", display_name="Kansas City Chiefs")


async def test_get_team_epa_resolves_team_and_delegates(stub_repo, stub_data_repo) -> None:
    stub_repo.team_by_id["12"] = _kc_team()
    expected = EPAStats(
        team=_kc_team(),
        season=2025,
        side="offense",
        epa_per_play=0.12,
        pass_epa_per_play=0.21,
        rush_epa_per_play=-0.02,
        success_rate=0.47,
    )
    stub_data_repo.epa_by_team[("12", 2025, "offense")] = expected
    service = NFLService(repo=stub_repo, data_repo=stub_data_repo)
    result = await service.get_team_epa("  12  ", season=2025, side="offense")
    assert result is expected
    assert stub_data_repo.calls == [("get_team_epa", {"team": "12", "season": 2025, "side": "offense"})]


async def test_get_team_epa_rejects_invalid_side(stub_repo, stub_data_repo) -> None:
    service = NFLService(repo=stub_repo, data_repo=stub_data_repo)
    with pytest.raises(ValueError):
        await service.get_team_epa("12", side="special")


async def test_get_team_epa_raises_when_data_repo_missing(stub_repo) -> None:
    stub_repo.team_by_id["12"] = _kc_team()
    service = NFLService(repo=stub_repo)
    with pytest.raises(RuntimeError, match="NFLDataPort"):
        await service.get_team_epa("12")


async def test_get_success_rate_delegates(stub_repo, stub_data_repo) -> None:
    stub_repo.team_by_id["12"] = _kc_team()
    stub_data_repo.success_rate_by_team[("12", 2025)] = SuccessRate(
        team=_kc_team(),
        season=2025,
        rate_offense=0.5,
        rate_defense=0.4,
        plays_offense=1100,
        plays_defense=1050,
    )
    service = NFLService(repo=stub_repo, data_repo=stub_data_repo)
    await service.get_success_rate("12", season=2025)
    assert stub_data_repo.calls == [("get_success_rate", {"team": "12", "season": 2025})]


async def test_get_third_down_rate_delegates(stub_repo, stub_data_repo) -> None:
    stub_repo.team_by_id["12"] = _kc_team()
    stub_data_repo.third_down_by_team[("12", 2025)] = ThirdDownStats(
        team=_kc_team(),
        season=2025,
        attempts_offense=130,
        conversions_offense=55,
        rate_offense=0.42,
        attempts_defense=125,
        conversions_defense_allowed=48,
        rate_defense=0.38,
    )
    service = NFLService(repo=stub_repo, data_repo=stub_data_repo)
    await service.get_third_down_rate("12", season=2025)
    assert stub_data_repo.calls[0][0] == "get_third_down_rate"


async def test_get_red_zone_efficiency_delegates(stub_repo, stub_data_repo) -> None:
    stub_repo.team_by_id["12"] = _kc_team()
    stub_data_repo.red_zone_by_team[("12", 2025)] = RedZoneStats(
        team=_kc_team(),
        season=2025,
        trips_offense=40,
        touchdowns_offense=26,
        td_rate_offense=0.65,
        trips_defense=35,
        touchdowns_defense_allowed=18,
        td_rate_defense=0.514,
    )
    service = NFLService(repo=stub_repo, data_repo=stub_data_repo)
    await service.get_red_zone_efficiency("12", season=2025)
    assert stub_data_repo.calls[0][0] == "get_red_zone_efficiency"


async def test_get_def_points_per_100_yards_delegates(stub_repo, stub_data_repo) -> None:
    stub_repo.team_by_id["12"] = _kc_team()
    stub_data_repo.def_points_by_team[("12", 2025)] = DefensiveEfficiency(
        team=_kc_team(),
        season=2025,
        yards_allowed=4200,
        points_allowed=320,
        points_per_100_yards=7.62,
        rating="poor",
    )
    service = NFLService(repo=stub_repo, data_repo=stub_data_repo)
    await service.get_def_points_per_100_yards("12", season=2025)
    assert stub_data_repo.calls[0][0] == "get_def_points_per_100_yards"


async def test_get_ats_record_default_situation_passes_none(stub_repo, stub_data_repo) -> None:
    stub_repo.team_by_id["12"] = _kc_team()
    stub_data_repo.ats_by_team[("12", 2025, None)] = ATSRecord(team=_kc_team(), season=2025, wins=8, losses=4, pushes=1)
    service = NFLService(repo=stub_repo, data_repo=stub_data_repo)
    await service.get_ats_record("12", season=2025)
    assert stub_data_repo.calls == [("get_ats_record", {"team": "12", "season": 2025, "situation": None})]


async def test_get_ats_record_with_situation(stub_repo, stub_data_repo) -> None:
    stub_repo.team_by_id["12"] = _kc_team()
    stub_data_repo.ats_by_team[("12", 2025, "home")] = ATSRecord(
        team=_kc_team(), season=2025, wins=4, losses=2, pushes=0, situation="home"
    )
    service = NFLService(repo=stub_repo, data_repo=stub_data_repo)
    await service.get_ats_record("12", season=2025, situation="home")
    assert stub_data_repo.calls[0][1]["situation"] == "home"


async def test_get_ats_record_rejects_unknown_situation(stub_repo, stub_data_repo) -> None:
    service = NFLService(repo=stub_repo, data_repo=stub_data_repo)
    with pytest.raises(ValueError):
        await service.get_ats_record("12", situation="rainy")


async def test_get_situational_record_delegates(stub_repo, stub_data_repo) -> None:
    stub_repo.team_by_id["12"] = _kc_team()
    record = SituationalRecord(
        team=_kc_team(),
        season=2025,
        situation="dome",
        su_wins=4,
        su_losses=1,
        su_ties=0,
        ats_wins=3,
        ats_losses=1,
        ats_pushes=1,
    )
    stub_data_repo.situational_by_team[("12", 2025, "dome")] = record
    service = NFLService(repo=stub_repo, data_repo=stub_data_repo)
    result = await service.get_situational_record("12", "dome", season=2025)
    assert result is record
    assert stub_data_repo.calls == [("get_situational_record", {"team": "12", "season": 2025, "situation": "dome"})]


async def test_get_situational_record_rejects_unknown_situation(stub_repo, stub_data_repo) -> None:
    service = NFLService(repo=stub_repo, data_repo=stub_data_repo)
    with pytest.raises(ValueError):
        await service.get_situational_record("12", "rainy")


async def test_get_ou_record_delegates(stub_repo, stub_data_repo) -> None:
    stub_repo.team_by_id["12"] = _kc_team()
    stub_data_repo.ou_by_team[("12", 2025)] = OURecord(team=_kc_team(), season=2025, overs=6, unders=3, pushes=1)
    service = NFLService(repo=stub_repo, data_repo=stub_data_repo)
    await service.get_ou_record("12", season=2025)
    assert stub_data_repo.calls == [("get_ou_record", {"team": "12", "season": 2025})]


async def test_get_qb_advanced_strips_id_and_delegates(stub_repo, stub_data_repo) -> None:
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
    stub_data_repo.qb_by_athlete[("3139477", 2025)] = qb
    service = NFLService(repo=stub_repo, data_repo=stub_data_repo)
    result = await service.get_qb_advanced("  3139477  ", season=2025)
    assert result is qb
    assert stub_data_repo.calls == [("get_qb_advanced", {"athlete_id": "3139477", "season": 2025})]


async def test_get_qb_advanced_rejects_blank_id(stub_repo, stub_data_repo) -> None:
    service = NFLService(repo=stub_repo, data_repo=stub_data_repo)
    with pytest.raises(ValueError):
        await service.get_qb_advanced("")


async def test_get_qb_advanced_raises_when_data_repo_missing(stub_repo) -> None:
    service = NFLService(repo=stub_repo)
    with pytest.raises(RuntimeError, match="NFLDataPort"):
        await service.get_qb_advanced("3139477")


async def test_get_current_odds_delegates_with_default_bookmaker(stub_repo, stub_odds_repo) -> None:
    odds = [
        GameOdds(
            game_id="abc",
            book="DraftKings",
            timestamp="2026-01-05T18:00:00Z",
            spread=-3.5,
            total=48.5,
            moneyline_home=-180,
            moneyline_away=160,
        )
    ]
    stub_odds_repo.odds_by_bookmaker["draftkings"] = odds
    service = NFLService(repo=stub_repo, odds_repo=stub_odds_repo)
    result = await service.get_current_odds()
    assert result == odds
    assert stub_odds_repo.calls == [("get_current_odds", {"bookmaker": "draftkings"})]


async def test_get_current_odds_raises_when_port_missing(stub_repo) -> None:
    service = NFLService(repo=stub_repo)
    with pytest.raises(RuntimeError, match="ODDS_API_KEY"):
        await service.get_current_odds()


async def test_get_game_weather_resolves_team_then_delegates(stub_repo, stub_weather_repo) -> None:
    stub_repo.team_by_id["12"] = _kc_team()
    stub_weather_repo.weather_by[("KC", "20250915")] = Weather(
        game_id="KC-20250915", is_indoor=False, temperature_f=72.0, wind_mph=8.0
    )
    service = NFLService(repo=stub_repo, weather_repo=stub_weather_repo)
    result = await service.get_game_weather("12", "20250915")
    assert result.temperature_f == 72.0
    assert stub_weather_repo.calls == [("get_weather", {"home_team_abbr": "KC", "date": "20250915"})]


async def test_get_game_weather_rejects_bad_date(stub_repo, stub_weather_repo) -> None:
    service = NFLService(repo=stub_repo, weather_repo=stub_weather_repo)
    with pytest.raises(ValueError):
        await service.get_game_weather("12", "2025-09-15")


async def test_get_game_weather_raises_when_port_missing(stub_repo) -> None:
    stub_repo.team_by_id["12"] = _kc_team()
    service = NFLService(repo=stub_repo)
    with pytest.raises(RuntimeError, match="WeatherPort"):
        await service.get_game_weather("12", "20250915")


async def test_resolve_uses_current_season_when_unspecified(stub_repo, stub_data_repo) -> None:
    stub_repo.team_by_id["12"] = _kc_team()
    stub_data_repo.success_rate_by_team[("12", 2026)] = SuccessRate(
        team=_kc_team(),
        season=2026,
        rate_offense=0.5,
        rate_defense=0.4,
        plays_offense=10,
        plays_defense=10,
    )
    # We can't predict the exact current season without freezing the clock, but we can
    # assert the call was made and the season is plausible (≥2024).
    stub_data_repo.success_rate_by_team[("12", 2025)] = stub_data_repo.success_rate_by_team[("12", 2026)]
    stub_data_repo.success_rate_by_team[("12", 2024)] = stub_data_repo.success_rate_by_team[("12", 2026)]
    service = NFLService(repo=stub_repo, data_repo=stub_data_repo)
    await service.get_success_rate("12")
    assert stub_data_repo.calls[0][1]["season"] >= 2024
