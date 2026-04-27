"""Outbound adapter — fetches current sportsbook lines from The Odds API.

The Odds API (https://the-odds-api.com) free tier permits 500 requests/month
and requires an API key. This adapter targets the snapshot endpoint:

    GET /v4/sports/americanfootball_nfl/odds
        ?apiKey=...&regions=us&markets=spreads,totals,h2h&bookmakers=draftkings

Each game yields one GameOdds row from the requested bookmaker. Spreads are
encoded from the home team's perspective (negative = home favored). Line
movement (open vs current) requires the paid historical endpoint and is not
exposed here.
"""

import logging
from typing import Any

import httpx

from ...domain.exceptions import UpstreamAPIError
from ...domain.models import GameOdds

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.the-odds-api.com"
_NFL_PATH = "/v4/sports/americanfootball_nfl/odds"
_DEFAULT_TIMEOUT = 30.0
_DEFAULT_BOOKMAKER = "draftkings"


def _check_response(response: httpx.Response, url: str) -> None:
    """Translate non-2xx HTTP responses into domain exceptions."""
    if response.status_code >= 400:
        raise UpstreamAPIError(f"Odds API error {response.status_code}: {url}")


class OddsAPIAdapter:
    """Fetches current NFL sportsbook lines from The Odds API."""

    def __init__(
        self,
        api_key: str,
        client: httpx.AsyncClient | None = None,
        base_url: str = _BASE_URL,
    ) -> None:
        """Initialize the adapter.

        Args:
            api_key: The Odds API key (from environment variable).
            client: Optional httpx.AsyncClient. Inject a MockTransport in tests.
            base_url: Override base URL (rarely needed).
        """
        if not api_key:
            raise ValueError("api_key is required")
        self._api_key = api_key
        self._client = client or httpx.AsyncClient(base_url=base_url, timeout=_DEFAULT_TIMEOUT)

    async def get_current_odds(self, bookmaker: str = _DEFAULT_BOOKMAKER) -> list[GameOdds]:
        """Return current lines for upcoming NFL games from a single bookmaker."""
        params = {
            "apiKey": self._api_key,
            "regions": "us",
            "markets": "spreads,totals,h2h",
            "bookmakers": bookmaker,
        }
        response = await self._client.get(_NFL_PATH, params=params)
        _check_response(response, _NFL_PATH)
        games = response.json()
        return [_parse_game_odds(game, bookmaker) for game in games if _has_bookmaker(game, bookmaker)]


def _has_bookmaker(game: dict[str, Any], bookmaker: str) -> bool:
    """Return True if the requested bookmaker has any markets for this game."""
    return any(b.get("key") == bookmaker for b in game.get("bookmakers", []))


def _parse_game_odds(game: dict[str, Any], bookmaker: str) -> GameOdds:
    """Map an Odds API game entry to a GameOdds for the named bookmaker."""
    book = next((b for b in game.get("bookmakers", []) if b.get("key") == bookmaker), {})
    markets = {m.get("key"): m for m in book.get("markets", [])}
    home_team = game.get("home_team", "")
    spread = _spread_for_home(markets.get("spreads"), home_team)
    total = _total_value(markets.get("totals"))
    ml_home, ml_away = _moneylines(markets.get("h2h"), home_team)
    return GameOdds(
        game_id=str(game.get("id", "")),
        book=book.get("title", bookmaker),
        timestamp=book.get("last_update", ""),
        spread=spread,
        moneyline_home=ml_home,
        moneyline_away=ml_away,
        total=total,
    )


def _spread_for_home(market: dict[str, Any] | None, home_team: str) -> float | None:
    """Pull the home team's spread (negative = favored) from the spreads market."""
    if not market:
        return None
    for outcome in market.get("outcomes", []):
        if outcome.get("name") == home_team:
            point = outcome.get("point")
            return float(point) if point is not None else None
    return None


def _total_value(market: dict[str, Any] | None) -> float | None:
    """Pull the over/under total from the totals market (Over and Under share the same point)."""
    if not market:
        return None
    outcomes = market.get("outcomes", [])
    if not outcomes:
        return None
    point = outcomes[0].get("point")
    return float(point) if point is not None else None


def _moneylines(market: dict[str, Any] | None, home_team: str) -> tuple[int | None, int | None]:
    """Pull (home_ml, away_ml) from the h2h market, both as American odds."""
    if not market:
        return None, None
    home_ml = away_ml = None
    for outcome in market.get("outcomes", []):
        price = outcome.get("price")
        if price is None:
            continue
        if outcome.get("name") == home_team:
            home_ml = int(price)
        else:
            away_ml = int(price)
    return home_ml, away_ml
