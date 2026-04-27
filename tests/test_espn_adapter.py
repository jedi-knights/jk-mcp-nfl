"""Tests for the ESPN HTTP adapter — uses httpx.MockTransport for hermetic responses."""

import httpx
import pytest

from nfl.domain.exceptions import NFLNotFoundError, UpstreamAPIError

from .conftest import json_response


async def test_get_teams_extracts_nested_team_list(make_espn_adapter) -> None:
    payload = {
        "sports": [
            {
                "leagues": [
                    {
                        "teams": [
                            {
                                "team": {
                                    "id": "12",
                                    "name": "Chiefs",
                                    "abbreviation": "KC",
                                    "location": "Kansas City",
                                    "displayName": "Kansas City Chiefs",
                                }
                            },
                            {
                                "team": {
                                    "id": "1",
                                    "name": "Falcons",
                                    "abbreviation": "ATL",
                                    "location": "Atlanta",
                                    "displayName": "Atlanta Falcons",
                                }
                            },
                        ]
                    }
                ]
            }
        ]
    }
    adapter = make_espn_adapter(json_response(payload))
    teams = await adapter.get_teams()
    assert [t.abbreviation for t in teams] == ["KC", "ATL"]


async def test_get_team_unwraps_team_key(make_espn_adapter) -> None:
    payload = {
        "team": {
            "id": "12",
            "name": "Chiefs",
            "abbreviation": "KC",
            "location": "Kansas City",
            "displayName": "Kansas City Chiefs",
            "logos": [{"href": "https://logo.example/kc.png"}],
        }
    }
    adapter = make_espn_adapter(json_response(payload))
    team = await adapter.get_team("12")
    assert team.id == "12"
    assert team.logo_url == "https://logo.example/kc.png"


async def test_get_team_missing_team_key_raises_not_found(make_espn_adapter) -> None:
    adapter = make_espn_adapter(json_response({}))
    with pytest.raises(NFLNotFoundError):
        await adapter.get_team("999")


async def test_404_translated_to_not_found(make_espn_adapter) -> None:
    adapter = make_espn_adapter(json_response({}, status=404))
    with pytest.raises(NFLNotFoundError):
        await adapter.get_teams()


async def test_500_translated_to_upstream_error(make_espn_adapter) -> None:
    adapter = make_espn_adapter(json_response({}, status=500))
    with pytest.raises(UpstreamAPIError):
        await adapter.get_teams()


async def test_get_scoreboard_no_date_omits_query(make_espn_adapter) -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"events": []})

    adapter = make_espn_adapter(handler)
    await adapter.get_scoreboard()
    assert "dates=" not in str(captured[0].url)


async def test_get_scoreboard_with_date_passes_dates_param(make_espn_adapter) -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"events": []})

    adapter = make_espn_adapter(handler)
    await adapter.get_scoreboard("20260105")
    assert "dates=20260105" in str(captured[0].url)


async def test_get_scoreboard_parses_event_status_and_week(make_espn_adapter) -> None:
    payload = {
        "events": [
            {
                "id": "401",
                "date": "2026-01-05T00:00Z",
                "name": "Chiefs at Bills",
                "shortName": "KC @ BUF",
                "week": {"number": 18},
                "competitions": [
                    {
                        "status": {"type": {"state": "post", "description": "Final"}},
                        "competitors": [
                            {
                                "team": {
                                    "id": "12",
                                    "abbreviation": "KC",
                                    "displayName": "Chiefs",
                                    "location": "Kansas City",
                                    "name": "Chiefs",
                                },
                                "homeAway": "away",
                                "score": "27",
                                "winner": True,
                            },
                            {
                                "team": {
                                    "id": "2",
                                    "abbreviation": "BUF",
                                    "displayName": "Bills",
                                    "location": "Buffalo",
                                    "name": "Bills",
                                },
                                "homeAway": "home",
                                "score": "24",
                                "winner": False,
                            },
                        ],
                    }
                ],
            }
        ]
    }
    adapter = make_espn_adapter(json_response(payload))
    matches = await adapter.get_scoreboard("20260105")
    assert len(matches) == 1
    assert matches[0].week == 18
    assert matches[0].status_type == "post"
    assert matches[0].competitors[0].score == "27"
    assert matches[0].competitors[0].winner is True


async def test_get_standings_walks_conference_division_tree(make_espn_adapter) -> None:
    payload = {
        "children": [
            {
                "name": "American Football Conference",
                "children": [
                    {
                        "name": "AFC East",
                        "standings": {
                            "entries": [
                                {
                                    "team": {
                                        "id": "2",
                                        "abbreviation": "BUF",
                                        "name": "Bills",
                                        "location": "Buffalo",
                                        "displayName": "Buffalo Bills",
                                    },
                                    "stats": [
                                        {"name": "wins", "value": 13},
                                        {"name": "losses", "value": 4},
                                        {"name": "ties", "value": 0},
                                        {"name": "winPercent", "value": 0.765},
                                        {"name": "pointsFor", "value": 480},
                                        {"name": "pointsAgainst", "value": 320},
                                        {"name": "differential", "value": 160},
                                    ],
                                }
                            ]
                        },
                    }
                ],
            }
        ]
    }
    adapter = make_espn_adapter(json_response(payload))
    standings = await adapter.get_standings()
    assert len(standings) == 1
    assert standings[0].team.conference == "AFC"
    assert standings[0].team.division == "East"
    assert standings[0].win_percent == 0.765
    assert standings[0].point_differential == 160


async def test_get_standings_skips_entries_missing_team(make_espn_adapter) -> None:
    payload = {
        "children": [{"name": "X", "children": [{"name": "AFC West", "standings": {"entries": [{"stats": []}]}}]}]
    }
    adapter = make_espn_adapter(json_response(payload))
    standings = await adapter.get_standings()
    assert standings == []


def _standings_payload_with(team_id: str, **stats: float) -> dict:
    base = {
        "wins": 10,
        "losses": 6,
        "ties": 1,
        "winPercent": 0.617,
        "pointsFor": 420,
        "pointsAgainst": 350,
        "differential": 70,
    }
    base.update(stats)
    return {
        "children": [
            {
                "name": "AFC",
                "children": [
                    {
                        "name": "AFC West",
                        "standings": {
                            "entries": [
                                {
                                    "team": {
                                        "id": team_id,
                                        "abbreviation": "KC",
                                        "name": "Chiefs",
                                        "location": "Kansas City",
                                        "displayName": "Kansas City Chiefs",
                                    },
                                    "stats": [{"name": k, "value": v} for k, v in base.items()],
                                }
                            ]
                        },
                    }
                ],
            }
        ]
    }


async def test_get_team_stats_derives_ppg_and_games(make_espn_adapter) -> None:
    adapter = make_espn_adapter(json_response(_standings_payload_with("12")))
    stats = await adapter.get_team_stats("12", season=2025)
    assert stats.team.id == "12"
    assert stats.season == 2025
    assert stats.games_played == 17
    assert stats.points_per_game == pytest.approx(420 / 17, rel=1e-3)
    assert stats.point_differential == 70


async def test_get_team_stats_raises_when_team_absent(make_espn_adapter) -> None:
    adapter = make_espn_adapter(json_response(_standings_payload_with("12")))
    with pytest.raises(NFLNotFoundError):
        await adapter.get_team_stats("999")


async def test_get_team_schedule_no_season_omits_query(make_espn_adapter) -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"events": []})

    adapter = make_espn_adapter(handler)
    await adapter.get_team_schedule("12")
    assert "/teams/12/schedule" in str(captured[0].url)
    assert "season=" not in str(captured[0].url)


async def test_get_team_schedule_passes_season(make_espn_adapter) -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"events": []})

    adapter = make_espn_adapter(handler)
    await adapter.get_team_schedule("12", season=2024)
    assert "season=2024" in str(captured[0].url)


def _schedule_event(
    event_id: str, home_id: str, away_id: str, away_score: str = "27", home_score: str = "24", winner_home: bool = False
) -> dict:
    return {
        "id": event_id,
        "date": f"2025-09-{int(event_id) % 30 + 1:02d}T00:00Z",
        "name": f"{away_id} at {home_id}",
        "shortName": f"{away_id} @ {home_id}",
        "week": {"number": 1},
        "competitions": [
            {
                "status": {"type": {"state": "post", "description": "Final"}},
                "competitors": [
                    {
                        "team": {
                            "id": home_id,
                            "abbreviation": home_id,
                            "name": home_id,
                            "location": home_id,
                            "displayName": home_id,
                        },
                        "homeAway": "home",
                        "score": home_score,
                        "winner": winner_home,
                    },
                    {
                        "team": {
                            "id": away_id,
                            "abbreviation": away_id,
                            "name": away_id,
                            "location": away_id,
                            "displayName": away_id,
                        },
                        "homeAway": "away",
                        "score": away_score,
                        "winner": not winner_home,
                    },
                ],
            }
        ],
    }


async def test_get_team_schedule_parses_events(make_espn_adapter) -> None:
    payload = {"events": [_schedule_event("1", home_id="2", away_id="12")]}
    adapter = make_espn_adapter(json_response(payload))
    matches = await adapter.get_team_schedule("12", season=2025)
    assert len(matches) == 1
    assert matches[0].competitors[0].team.id == "2"


async def test_get_roster_flattens_position_groups(make_espn_adapter) -> None:
    payload = {
        "athletes": [
            {
                "position": "offense",
                "items": [
                    {
                        "id": "1",
                        "fullName": "Patrick Mahomes",
                        "position": {"abbreviation": "QB"},
                        "jersey": "15",
                        "displayHeight": "6'3\"",
                        "displayWeight": "230 lbs",
                        "age": 30,
                    },
                ],
            },
            {
                "position": "defense",
                "items": [
                    {"id": "2", "fullName": "Chris Jones", "position": {"abbreviation": "DT"}, "jersey": "95"},
                ],
            },
        ]
    }
    adapter = make_espn_adapter(json_response(payload))
    roster = await adapter.get_roster("12")
    assert [a.id for a in roster] == ["1", "2"]
    assert roster[0].position == "QB"
    assert roster[0].jersey == "15"
    assert roster[0].age == 30


async def test_get_roster_handles_unwrapped_athletes_list(make_espn_adapter) -> None:
    payload = {
        "athletes": [
            {"id": "1", "fullName": "Patrick Mahomes", "position": {"abbreviation": "QB"}},
        ]
    }
    adapter = make_espn_adapter(json_response(payload))
    roster = await adapter.get_roster("12")
    assert roster[0].full_name == "Patrick Mahomes"


async def test_get_injuries_league_wide_flattens_team_buckets(make_espn_adapter) -> None:
    payload = {
        "injuries": [
            {
                "team": {"id": "12", "name": "Chiefs", "abbreviation": "KC", "location": "KC", "displayName": "Chiefs"},
                "injuries": [
                    {
                        "athlete": {"displayName": "Travis Kelce", "position": {"abbreviation": "TE"}},
                        "status": "Questionable",
                        "shortComment": "knee",
                    },
                ],
            },
            {
                "team": {"id": "2", "name": "Bills", "abbreviation": "BUF", "location": "BUF", "displayName": "Bills"},
                "injuries": [
                    {"athlete": {"displayName": "Stefon Diggs", "position": {"abbreviation": "WR"}}, "status": "Out"},
                ],
            },
        ]
    }
    adapter = make_espn_adapter(json_response(payload))
    injuries = await adapter.get_injuries()
    assert {i.player_name for i in injuries} == {"Travis Kelce", "Stefon Diggs"}
    assert injuries[0].team.id == "12"


async def test_get_injuries_team_scoped_filters_url(make_espn_adapter) -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"injuries": []})

    adapter = make_espn_adapter(handler)
    await adapter.get_injuries("12")
    assert "/teams/12" in str(captured[0].url) or "team=12" in str(captured[0].url)


async def test_get_athlete_parses_profile(make_espn_adapter) -> None:
    payload = {
        "athlete": {
            "id": "3139477",
            "fullName": "Patrick Mahomes",
            "position": {"abbreviation": "QB"},
            "jersey": "15",
            "displayHeight": "6'3\"",
            "displayWeight": "230 lbs",
            "age": 30,
            "team": {
                "id": "12",
                "name": "Chiefs",
                "abbreviation": "KC",
                "location": "Kansas City",
                "displayName": "Kansas City Chiefs",
            },
        }
    }
    adapter = make_espn_adapter(json_response(payload))
    athlete = await adapter.get_athlete("3139477")
    assert athlete.full_name == "Patrick Mahomes"
    assert athlete.team is not None
    assert athlete.team.abbreviation == "KC"


async def test_get_athlete_missing_key_raises_not_found(make_espn_adapter) -> None:
    adapter = make_espn_adapter(json_response({}))
    with pytest.raises(NFLNotFoundError):
        await adapter.get_athlete("999")


async def test_get_news_parses_articles_and_passes_limit(make_espn_adapter) -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={
                "articles": [
                    {
                        "headline": "Trade rumors",
                        "description": "...",
                        "published": "2026-01-05T18:00:00Z",
                        "links": {"web": {"href": "https://espn.com/x"}},
                    },
                ]
            },
        )

    adapter = make_espn_adapter(handler)
    news = await adapter.get_news(limit=5)
    assert len(news) == 1
    assert news[0].url == "https://espn.com/x"
    assert "limit=5" in str(captured[0].url)


async def test_get_news_team_scoped_passes_team_param(make_espn_adapter) -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"articles": []})

    adapter = make_espn_adapter(handler)
    await adapter.get_news("12", limit=10)
    assert "team=12" in str(captured[0].url)
