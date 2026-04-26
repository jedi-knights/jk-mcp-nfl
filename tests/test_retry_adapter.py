"""Tests for the retry decorator — exponential backoff, 404 fast-path."""

from typing import Any

import pytest

from nfl.adapters.outbound.retry_adapter import RetryingAdapter
from nfl.domain.exceptions import NFLNotFoundError, UpstreamAPIError


class _Flaky:
    def __init__(self, fails_before_success: int) -> None:
        self.attempts = 0
        self._fails = fails_before_success

    async def get_teams(self) -> list[Any]:
        self.attempts += 1
        if self.attempts <= self._fails:
            raise UpstreamAPIError("boom")
        return ["ok"]

    async def get_team(self, team_id: str) -> Any:
        raise NFLNotFoundError(team_id)

    async def get_scoreboard(self, date: str | None = None) -> list[Any]:
        return []

    async def get_standings(self) -> list[Any]:
        return []


async def test_retries_until_success() -> None:
    delays: list[float] = []

    async def sleep(d: float) -> None:
        delays.append(d)

    inner = _Flaky(fails_before_success=2)
    retry = RetryingAdapter(inner, max_attempts=3, delay_seconds=1.0, sleep=sleep)
    result = await retry.get_teams()
    assert result == ["ok"]
    assert inner.attempts == 3
    assert delays == [1.0, 2.0]


async def test_gives_up_after_max_attempts() -> None:
    async def sleep(_: float) -> None:
        return None

    inner = _Flaky(fails_before_success=99)
    retry = RetryingAdapter(inner, max_attempts=2, delay_seconds=0.1, sleep=sleep)
    with pytest.raises(UpstreamAPIError):
        await retry.get_teams()
    assert inner.attempts == 2


async def test_not_found_does_not_retry() -> None:
    attempts: list[None] = []

    async def sleep(_: float) -> None:
        attempts.append(None)

    inner = _Flaky(fails_before_success=0)
    retry = RetryingAdapter(inner, max_attempts=3, delay_seconds=0.1, sleep=sleep)
    with pytest.raises(NFLNotFoundError):
        await retry.get_team("999")
    assert attempts == []
