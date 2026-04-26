"""Outbound adapter — translates domain calls into ESPN API HTTP requests.

This is the only place in the codebase that knows about:
- The ESPN API host and URL structure
- How to issue HTTP requests and translate non-2xx responses into domain errors

The wire-format → domain-model mapping lives in parsers.py so this module
stays focused on transport.
"""

import logging
from typing import Any

import httpx

from ...domain.exceptions import NFLNotFoundError, UpstreamAPIError
from ...domain.models import Match, Standing, Team
from .parsers import _parse_match, _parse_standing, _parse_team, _split_conference_division

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://site.api.espn.com"
_LEAGUE_PATH = "/apis/site/v2/sports/football/nfl"
# Standings live on the /apis/v2 surface — the /apis/site/v2 path returns an empty {}.
_STANDINGS_PATH = "/apis/v2/sports/football/nfl/standings"


def _check_response(response: httpx.Response, path: str) -> None:
    """Raise a domain exception for any non-2xx HTTP status.

    Raises:
        NFLNotFoundError: If the server returned HTTP 404.
        UpstreamAPIError: If the server returned any other 4xx or 5xx status.
    """
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise NFLNotFoundError(f"Not found: {path}") from exc
        raise UpstreamAPIError(f"Upstream error {exc.response.status_code}: {path}") from exc


class ESPNAdapter:
    """Calls the ESPN public API for NFL data.

    The underlying httpx.AsyncClient is created once at construction and reused
    for all requests so the TCP connection pool is retained across calls —
    avoiding a fresh TCP+TLS handshake on every API call.
    """

    def __init__(self, base_url: str = _DEFAULT_BASE_URL, client: httpx.AsyncClient | None = None) -> None:
        """Initialize the adapter with an optional HTTP client.

        Args:
            base_url: Base URL of the ESPN API. Defaults to https://site.api.espn.com.
            client: An httpx.AsyncClient instance to reuse across all requests.
                Inject a pre-configured mock in tests.
        """
        self._client = client or httpx.AsyncClient(base_url=base_url, timeout=30.0)

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute a GET request and return the parsed JSON body."""
        logger.debug("GET %s params=%s", path, params)
        response = await self._client.get(path, params=params or {})
        _check_response(response, path)
        return response.json()

    async def get_teams(self) -> list[Team]:
        """Return all active NFL teams."""
        data = await self._get(f"{_LEAGUE_PATH}/teams", {"limit": 100})
        raw_teams = data.get("sports", [{}])[0].get("leagues", [{}])[0].get("teams", [])
        return [_parse_team(t) for t in raw_teams]

    async def get_team(self, team_id: str) -> Team:
        """Return a single team by its ESPN team ID.

        Raises:
            NFLNotFoundError: If no team with that ID exists.
        """
        data = await self._get(f"{_LEAGUE_PATH}/teams/{team_id}")
        raw = data.get("team")
        if not raw:
            raise NFLNotFoundError(f"Team not found: {team_id}")
        return _parse_team(raw)

    async def get_scoreboard(self, date: str | None = None) -> list[Match]:
        """Return matches on the given date, or the current week if date is None.

        Args:
            date: Optional date string in YYYYMMDD format.
        """
        params: dict[str, Any] = {}
        if date:
            params["dates"] = date
        data = await self._get(f"{_LEAGUE_PATH}/scoreboard", params)
        return [_parse_match(e) for e in data.get("events", [])]

    async def get_standings(self) -> list[Standing]:
        """Return the current NFL standings ordered by win percentage descending."""
        data = await self._get(_STANDINGS_PATH)
        standings: list[Standing] = []
        for conference in data.get("children", []):
            for division in conference.get("children", []):
                conf, div = _split_conference_division(division.get("name", ""))
                for entry in division.get("standings", {}).get("entries", []):
                    parsed = _parse_standing(entry, conf, div)
                    if parsed is not None:
                        standings.append(parsed)
        return sorted(standings, key=lambda s: (s.win_percent, s.point_differential), reverse=True)
