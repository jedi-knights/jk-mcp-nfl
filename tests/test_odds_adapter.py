"""Tests for the Odds API adapter — auth, parsing, error translation."""

import httpx
import pytest

from nfl.adapters.outbound.odds_adapter import (
    OddsAPIAdapter,
    _moneylines,
    _parse_game_odds,
    _spread_for_home,
    _total_value,
)
from nfl.domain.exceptions import UpstreamAPIError


def _make_adapter(handler) -> OddsAPIAdapter:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="https://test.invalid")
    return OddsAPIAdapter(api_key="test-key", client=client)


def _sample_game(bookmaker: str = "draftkings") -> dict:
    return {
        "id": "abc123",
        "sport_key": "americanfootball_nfl",
        "commence_time": "2026-01-05T18:00:00Z",
        "home_team": "Kansas City Chiefs",
        "away_team": "Buffalo Bills",
        "bookmakers": [
            {
                "key": bookmaker,
                "title": bookmaker.title(),
                "last_update": "2026-01-05T17:55:00Z",
                "markets": [
                    {
                        "key": "spreads",
                        "outcomes": [
                            {"name": "Kansas City Chiefs", "price": -110, "point": -3.5},
                            {"name": "Buffalo Bills", "price": -110, "point": 3.5},
                        ],
                    },
                    {
                        "key": "totals",
                        "outcomes": [
                            {"name": "Over", "price": -110, "point": 48.5},
                            {"name": "Under", "price": -110, "point": 48.5},
                        ],
                    },
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Kansas City Chiefs", "price": -180},
                            {"name": "Buffalo Bills", "price": 160},
                        ],
                    },
                ],
            }
        ],
    }


def test_constructor_rejects_blank_api_key() -> None:
    with pytest.raises(ValueError):
        OddsAPIAdapter(api_key="")


async def test_get_current_odds_passes_api_key_and_markets() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=[_sample_game()])

    adapter = _make_adapter(handler)
    await adapter.get_current_odds()
    url = str(captured[0].url)
    assert "apiKey=test-key" in url
    assert "spreads" in url
    assert "bookmakers=draftkings" in url


async def test_get_current_odds_parses_one_row_per_game() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[_sample_game(), _sample_game()])

    adapter = _make_adapter(handler)
    odds = await adapter.get_current_odds()
    assert len(odds) == 2
    first = odds[0]
    assert first.game_id == "abc123"
    assert first.book == "Draftkings"
    assert first.spread == -3.5
    assert first.total == 48.5
    assert first.moneyline_home == -180
    assert first.moneyline_away == 160


async def test_get_current_odds_skips_games_without_requested_bookmaker() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[_sample_game(bookmaker="fanduel")])

    adapter = _make_adapter(handler)
    odds = await adapter.get_current_odds(bookmaker="draftkings")
    assert odds == []


async def test_500_translates_to_upstream_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={})

    adapter = _make_adapter(handler)
    with pytest.raises(UpstreamAPIError):
        await adapter.get_current_odds()


def test_spread_for_home_handles_missing_market() -> None:
    assert _spread_for_home(None, "KC") is None


def test_total_value_handles_missing_market() -> None:
    assert _total_value(None) is None


def test_moneylines_returns_none_pair_when_missing() -> None:
    assert _moneylines(None, "KC") == (None, None)


def test_parse_game_odds_handles_partial_data() -> None:
    """Sparse game with only a spreads market still parses without crashing."""
    game = {
        "id": "x",
        "home_team": "KC",
        "away_team": "BUF",
        "bookmakers": [
            {
                "key": "draftkings",
                "title": "DraftKings",
                "last_update": "now",
                "markets": [
                    {
                        "key": "spreads",
                        "outcomes": [
                            {"name": "KC", "price": -110, "point": -2.0},
                            {"name": "BUF", "price": -110, "point": 2.0},
                        ],
                    }
                ],
            }
        ],
    }
    odds = _parse_game_odds(game, "draftkings")
    assert odds.spread == -2.0
    assert odds.total is None
    assert odds.moneyline_home is None
