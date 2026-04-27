"""Tests for the domain dataclasses — minimal, mostly construction & defaults."""

from nfl.domain.exceptions import NFLError, NFLNotFoundError, SeasonNotAvailableError, UpstreamAPIError
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


def _make_team(team_id: str = "1") -> Team:
    return Team(id=team_id, name="x", abbreviation="x", location="x", display_name="x")


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
    assert issubclass(SeasonNotAvailableError, NFLError)


def test_team_stats_carries_efficiency_metrics() -> None:
    stats = TeamStats(
        team=_make_team(),
        season=2025,
        games_played=10,
        points_per_game=27.4,
        yards_per_game_allowed=312.1,
        yards_per_play=5.8,
        point_differential=85,
        turnover_differential=7,
    )
    assert stats.points_per_game == 27.4
    assert stats.turnover_differential == 7


def test_ats_record_defaults_situation_to_none() -> None:
    record = ATSRecord(team=_make_team(), season=2025, wins=8, losses=4, pushes=1)
    assert record.situation is None


def test_ats_record_accepts_situation() -> None:
    record = ATSRecord(team=_make_team(), season=2025, wins=4, losses=2, pushes=0, situation="home")
    assert record.situation == "home"


def test_ou_record_tracks_overs_unders_pushes() -> None:
    record = OURecord(team=_make_team(), season=2025, overs=6, unders=3, pushes=1)
    assert record.overs == 6
    assert record.pushes == 1


def test_situational_record_holds_su_and_ats() -> None:
    record = SituationalRecord(
        team=_make_team(),
        season=2025,
        situation="dome",
        su_wins=4,
        su_losses=1,
        su_ties=0,
        ats_wins=3,
        ats_losses=1,
        ats_pushes=1,
    )
    assert record.situation == "dome"
    assert record.su_wins == 4
    assert record.ats_pushes == 1


def test_red_zone_stats_holds_offense_and_defense() -> None:
    rz = RedZoneStats(
        team=_make_team(),
        season=2025,
        trips_offense=40,
        touchdowns_offense=26,
        td_rate_offense=0.65,
        trips_defense=35,
        touchdowns_defense_allowed=18,
        td_rate_defense=0.514,
    )
    assert rz.td_rate_offense == 0.65
    assert rz.td_rate_defense == 0.514


def test_third_down_stats_holds_offense_and_defense() -> None:
    td = ThirdDownStats(
        team=_make_team(),
        season=2025,
        attempts_offense=130,
        conversions_offense=55,
        rate_offense=0.423,
        attempts_defense=125,
        conversions_defense_allowed=48,
        rate_defense=0.384,
    )
    assert td.rate_offense == 0.423


def test_success_rate_holds_offense_and_defense() -> None:
    sr = SuccessRate(
        team=_make_team(),
        season=2025,
        rate_offense=0.47,
        rate_defense=0.39,
        plays_offense=1100,
        plays_defense=1050,
    )
    assert sr.rate_offense == 0.47
    assert sr.plays_defense == 1050


def test_epa_stats_tags_side() -> None:
    epa = EPAStats(
        team=_make_team(),
        season=2025,
        side="offense",
        epa_per_play=0.12,
        pass_epa_per_play=0.21,
        rush_epa_per_play=-0.02,
        success_rate=0.47,
    )
    assert epa.side == "offense"
    assert epa.pass_epa_per_play == 0.21


def test_qb_advanced_stats_tracks_efficiency() -> None:
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
    assert qb.cpoe == 3.2
    assert qb.td_int_ratio == 4.0


def test_defensive_efficiency_carries_rating_band() -> None:
    de = DefensiveEfficiency(
        team=_make_team(),
        season=2025,
        yards_allowed=4200,
        points_allowed=320,
        points_per_100_yards=7.62,
        rating="poor",
    )
    assert de.rating == "poor"
    assert de.points_per_100_yards == 7.62


def test_weather_dome_marks_indoor_with_no_metrics() -> None:
    weather = Weather(game_id="401", is_indoor=True)
    assert weather.is_indoor is True
    assert weather.temperature_f is None
    assert weather.wind_mph is None


def test_weather_outdoor_carries_full_forecast() -> None:
    weather = Weather(
        game_id="401",
        is_indoor=False,
        temperature_f=42.5,
        wind_mph=14.0,
        precipitation_chance=0.6,
        condition="Rain",
    )
    assert weather.temperature_f == 42.5
    assert weather.condition == "Rain"


def test_game_odds_optional_fields_default_to_none() -> None:
    odds = GameOdds(game_id="401", book="DraftKings", timestamp="2026-01-05T18:00:00Z")
    assert odds.spread is None
    assert odds.moneyline_home is None
    assert odds.total is None


def test_player_injury_minimal_construction() -> None:
    injury = PlayerInjury(player_name="Patrick Mahomes", position="QB", status="Questionable")
    assert injury.team is None
    assert injury.description is None


def test_news_item_optional_url() -> None:
    news = NewsItem(headline="Trade rumors", description="...", published="2026-01-05T18:00:00Z")
    assert news.url is None


def test_athlete_optional_team_and_metadata() -> None:
    athlete = Athlete(id="3139477", full_name="Patrick Mahomes", position="QB")
    assert athlete.team is None
    assert athlete.jersey is None


def test_head_to_head_zero_matches_default() -> None:
    h2h = HeadToHead(team_a=_make_team("1"), team_b=_make_team("2"), team_a_wins=0, team_b_wins=0, ties=0)
    assert h2h.matches == []
