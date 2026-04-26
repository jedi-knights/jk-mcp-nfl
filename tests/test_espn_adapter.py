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
