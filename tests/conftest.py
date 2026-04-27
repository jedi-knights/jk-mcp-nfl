"""Shared fixtures for the NFL MCP server tests."""

from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest

from nfl.adapters.outbound.espn_adapter import ESPNAdapter


@pytest.fixture
def make_espn_adapter() -> Callable[[Callable[[httpx.Request], httpx.Response]], ESPNAdapter]:
    """Build an ESPNAdapter wired to a MockTransport with the given handler."""

    def factory(handler: Callable[[httpx.Request], httpx.Response]) -> ESPNAdapter:
        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport, base_url="https://test.invalid")
        return ESPNAdapter(client=client)

    return factory


def json_response(payload: dict[str, Any], status: int = 200) -> Callable[[httpx.Request], httpx.Response]:
    """Return a MockTransport handler that always returns `payload` with `status`."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=payload)

    return handler


class StubRepo:
    """Minimal in-memory NFLAPIPort double for service tests."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.teams: list[Any] = []
        self.team_by_id: dict[str, Any] = {}
        self.scoreboard: list[Any] = []
        self.standings: list[Any] = []
        self.team_stats_by_id: dict[str, Any] = {}
        self.schedule_by_team: dict[str, list[Any]] = {}
        self.roster_by_team: dict[str, list[Any]] = {}
        self.injuries: list[Any] = []
        self.injuries_by_team: dict[str, list[Any]] = {}
        self.athlete_by_id: dict[str, Any] = {}
        self.news: list[Any] = []
        self.news_by_team: dict[str, list[Any]] = {}
        self.raise_on: dict[str, Exception] = {}

    def _record(self, name: str, **kwargs: Any) -> None:
        self.calls.append((name, kwargs))
        exc = self.raise_on.get(name)
        if exc is not None:
            raise exc

    async def get_teams(self) -> list[Any]:
        self._record("get_teams")
        return self.teams

    async def get_team(self, team_id: str) -> Any:
        self._record("get_team", team_id=team_id)
        return self.team_by_id[team_id]

    async def get_scoreboard(self, date: str | None = None) -> list[Any]:
        self._record("get_scoreboard", date=date)
        return self.scoreboard

    async def get_standings(self) -> list[Any]:
        self._record("get_standings")
        return self.standings

    async def get_team_stats(self, team_id: str, season: int | None = None) -> Any:
        self._record("get_team_stats", team_id=team_id, season=season)
        return self.team_stats_by_id[team_id]

    async def get_team_schedule(self, team_id: str, season: int | None = None) -> list[Any]:
        self._record("get_team_schedule", team_id=team_id, season=season)
        return self.schedule_by_team.get(team_id, [])

    async def get_roster(self, team_id: str) -> list[Any]:
        self._record("get_roster", team_id=team_id)
        return self.roster_by_team[team_id]

    async def get_injuries(self, team_id: str | None = None) -> list[Any]:
        self._record("get_injuries", team_id=team_id)
        return self.injuries_by_team[team_id] if team_id is not None else self.injuries

    async def get_athlete(self, athlete_id: str) -> Any:
        self._record("get_athlete", athlete_id=athlete_id)
        return self.athlete_by_id[athlete_id]

    async def get_news(self, team_id: str | None = None, limit: int = 10) -> list[Any]:
        self._record("get_news", team_id=team_id, limit=limit)
        return self.news_by_team[team_id] if team_id is not None else self.news


@pytest.fixture
def stub_repo() -> StubRepo:
    """Fresh StubRepo per test."""
    return StubRepo()


class StubDataRepo:
    """In-memory NFLDataPort double for service tests.

    Each method records its call args and returns a pre-set value (or raises
    a pre-set exception) so service-layer tests can exercise validation +
    delegation without touching polars or HTTP.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.epa_by_team: dict[tuple[str, int, str], Any] = {}
        self.success_rate_by_team: dict[tuple[str, int], Any] = {}
        self.third_down_by_team: dict[tuple[str, int], Any] = {}
        self.red_zone_by_team: dict[tuple[str, int], Any] = {}
        self.def_points_by_team: dict[tuple[str, int], Any] = {}
        self.qb_by_athlete: dict[tuple[str, int], Any] = {}
        self.ats_by_team: dict[tuple[str, int, str | None], Any] = {}
        self.ou_by_team: dict[tuple[str, int], Any] = {}
        self.situational_by_team: dict[tuple[str, int, str], Any] = {}
        self.raise_on: dict[str, Exception] = {}

    def _record(self, name: str, **kwargs: Any) -> None:
        self.calls.append((name, kwargs))
        exc = self.raise_on.get(name)
        if exc is not None:
            raise exc

    async def get_team_epa(self, team: Any, season: int, side: str) -> Any:
        self._record("get_team_epa", team=team.id, season=season, side=side)
        return self.epa_by_team[(team.id, season, side)]

    async def get_success_rate(self, team: Any, season: int) -> Any:
        self._record("get_success_rate", team=team.id, season=season)
        return self.success_rate_by_team[(team.id, season)]

    async def get_third_down_rate(self, team: Any, season: int) -> Any:
        self._record("get_third_down_rate", team=team.id, season=season)
        return self.third_down_by_team[(team.id, season)]

    async def get_red_zone_efficiency(self, team: Any, season: int) -> Any:
        self._record("get_red_zone_efficiency", team=team.id, season=season)
        return self.red_zone_by_team[(team.id, season)]

    async def get_def_points_per_100_yards(self, team: Any, season: int) -> Any:
        self._record("get_def_points_per_100_yards", team=team.id, season=season)
        return self.def_points_by_team[(team.id, season)]

    async def get_qb_advanced(self, athlete_id: str, season: int) -> Any:
        self._record("get_qb_advanced", athlete_id=athlete_id, season=season)
        return self.qb_by_athlete[(athlete_id, season)]

    async def get_ats_record(self, team: Any, season: int, situation: str | None = None) -> Any:
        self._record("get_ats_record", team=team.id, season=season, situation=situation)
        return self.ats_by_team[(team.id, season, situation)]

    async def get_ou_record(self, team: Any, season: int) -> Any:
        self._record("get_ou_record", team=team.id, season=season)
        return self.ou_by_team[(team.id, season)]

    async def get_situational_record(self, team: Any, season: int, situation: str) -> Any:
        self._record("get_situational_record", team=team.id, season=season, situation=situation)
        return self.situational_by_team[(team.id, season, situation)]


@pytest.fixture
def stub_data_repo() -> StubDataRepo:
    """Fresh StubDataRepo per test."""
    return StubDataRepo()


class StubWeatherRepo:
    """In-memory WeatherPort double for service tests."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.weather_by: dict[tuple[str, str], Any] = {}

    async def get_weather(self, home_team_abbr: str, date_yyyymmdd: str) -> Any:
        self.calls.append(("get_weather", {"home_team_abbr": home_team_abbr, "date": date_yyyymmdd}))
        return self.weather_by[(home_team_abbr, date_yyyymmdd)]


@pytest.fixture
def stub_weather_repo() -> StubWeatherRepo:
    return StubWeatherRepo()


class StubOddsRepo:
    """In-memory OddsPort double for service tests."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.odds_by_bookmaker: dict[str, list[Any]] = {}

    async def get_current_odds(self, bookmaker: str = "draftkings") -> list[Any]:
        self.calls.append(("get_current_odds", {"bookmaker": bookmaker}))
        return self.odds_by_bookmaker.get(bookmaker, [])


@pytest.fixture
def stub_odds_repo() -> StubOddsRepo:
    return StubOddsRepo()


async def collect(awaitable: Awaitable[Any]) -> Any:
    """Tiny helper for tests that want to await an expression inline."""
    return await awaitable
