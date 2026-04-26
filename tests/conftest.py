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


@pytest.fixture
def stub_repo() -> StubRepo:
    """Fresh StubRepo per test."""
    return StubRepo()


async def collect(awaitable: Awaitable[Any]) -> Any:
    """Tiny helper for tests that want to await an expression inline."""
    return await awaitable
