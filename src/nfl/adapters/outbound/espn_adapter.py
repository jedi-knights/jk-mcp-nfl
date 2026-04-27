"""Outbound adapter — translates domain calls into ESPN API HTTP requests.

This is the only place in the codebase that knows about:
- The ESPN API host and URL structure
- How to issue HTTP requests and translate non-2xx responses into domain errors

The wire-format → domain-model mapping lives in parsers.py so this module
stays focused on transport.
"""

import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from ...domain.exceptions import NFLNotFoundError, UpstreamAPIError
from ...domain.models import Athlete, Match, NewsItem, PlayerInjury, Standing, Team, TeamStats
from .parsers import (
    _parse_athlete,
    _parse_match,
    _parse_news_item,
    _parse_player_injury,
    _parse_standing,
    _parse_team,
    _split_conference_division,
)

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

    async def get_team_stats(self, team_id: str, season: int | None = None) -> TeamStats:
        """Return season-level stats derived from the standings entry for a team.

        The site standings endpoint exposes wins/losses/ties, points for/against
        and point differential. Yardage and turnover differential are not
        carried in this payload and remain None.

        Raises:
            NFLNotFoundError: If no standings entry exists for the team ID.
        """
        for s in await self.get_standings():
            if s.team.id == team_id:
                return _team_stats_from_standing(s, season)
        raise NFLNotFoundError(f"Team not found in standings: {team_id}")

    async def get_team_schedule(self, team_id: str, season: int | None = None) -> list[Match]:
        """Return a team's schedule for the given season.

        Args:
            team_id: ESPN numeric team ID.
            season: Optional season year. If omitted, ESPN returns the current season.
        """
        params: dict[str, Any] = {}
        if season is not None:
            params["season"] = season
        data = await self._get(f"{_LEAGUE_PATH}/teams/{team_id}/schedule", params)
        return [_parse_match(e) for e in data.get("events", [])]

    async def get_roster(self, team_id: str) -> list[Athlete]:
        """Return the active roster for a team.

        ESPN groups roster entries by position type ("offense", "defense",
        "specialTeam") under `athletes[].items`. We flatten across groups but
        also tolerate a flat list shape for forward-compatibility.
        """
        data = await self._get(f"{_LEAGUE_PATH}/teams/{team_id}/roster")
        return _flatten_roster(data.get("athletes", []))

    async def get_injuries(self, team_id: str | None = None) -> list[PlayerInjury]:
        """Return current injury report entries.

        Args:
            team_id: Optional ESPN numeric team ID. When given, hits the
                team-scoped injuries endpoint. When None, walks the league-wide
                report and flattens across team buckets.
        """
        path = f"{_LEAGUE_PATH}/teams/{team_id}/injuries" if team_id else f"{_LEAGUE_PATH}/injuries"
        data = await self._get(path)
        return _flatten_injuries(data.get("injuries", []))

    async def get_athlete(self, athlete_id: str) -> Athlete:
        """Return a single athlete's profile.

        Raises:
            NFLNotFoundError: If no athlete with that ID exists.
        """
        data = await self._get(f"{_LEAGUE_PATH}/athletes/{athlete_id}")
        raw = data.get("athlete")
        if not raw:
            raise NFLNotFoundError(f"Athlete not found: {athlete_id}")
        return _parse_athlete(raw)

    async def get_news(self, team_id: str | None = None, limit: int = 10) -> list[NewsItem]:
        """Return recent NFL news articles.

        Args:
            team_id: Optional ESPN numeric team ID to scope the feed to a team.
            limit: Maximum number of articles to return.
        """
        params: dict[str, Any] = {"limit": limit}
        if team_id is not None:
            params["team"] = team_id
        data = await self._get(f"{_LEAGUE_PATH}/news", params)
        return [_parse_news_item(a) for a in data.get("articles", [])]


def _flatten_roster(raw: list[dict[str, Any]]) -> list[Athlete]:
    """Flatten ESPN's grouped or flat roster shape into a single athlete list."""
    flat: list[Athlete] = []
    for entry in raw:
        items = entry.get("items")
        if isinstance(items, list):
            flat.extend(_parse_athlete(item) for item in items)
        else:
            flat.append(_parse_athlete(entry))
    return flat


def _flatten_injuries(raw: list[dict[str, Any]]) -> list[PlayerInjury]:
    """Flatten ESPN's per-team injury buckets into one list, tagging each with its team."""
    flat: list[PlayerInjury] = []
    for bucket in raw:
        team_raw = bucket.get("team")
        team = _parse_team(team_raw) if isinstance(team_raw, dict) else None
        for entry in bucket.get("injuries", []):
            flat.append(_parse_player_injury(entry, team))
    return flat


def _team_stats_from_standing(standing: Standing, season: int | None) -> TeamStats:
    """Project a Standing onto the TeamStats shape, filling unavailable fields with None."""
    games = standing.wins + standing.losses + standing.ties
    ppg = (standing.points_for / games) if games else None
    return TeamStats(
        team=standing.team,
        season=season if season is not None else _current_season(),
        games_played=games,
        points_per_game=ppg,
        point_differential=standing.point_differential,
    )


def _current_season() -> int:
    """Return the NFL season year named after its September start.

    Aug–Dec uses the calendar year; Jan–Jul uses the previous calendar year.
    """
    today = datetime.now(UTC)
    return today.year if today.month >= 8 else today.year - 1
