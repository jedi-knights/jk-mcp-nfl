"""Tests for the generic RetryingProxy — works on any async port."""

import pytest

from nfl.adapters.outbound.retry_proxy import RetryingProxy
from nfl.domain.exceptions import NFLNotFoundError, SeasonNotAvailableError, UpstreamAPIError


class _Flaky:
    def __init__(self, fails_before_success: int) -> None:
        self.attempts = 0
        self._fails = fails_before_success

    async def get_data(self, key: str) -> str:
        self.attempts += 1
        if self.attempts <= self._fails:
            raise UpstreamAPIError("transient")
        return f"data-{key}"

    async def get_missing(self, key: str) -> str:
        raise NFLNotFoundError(key)

    async def get_old_season(self, season: int) -> str:
        raise SeasonNotAvailableError(str(season))


async def test_retries_until_success() -> None:
    delays: list[float] = []

    async def sleep(d: float) -> None:
        delays.append(d)

    inner = _Flaky(fails_before_success=2)
    proxy = RetryingProxy(inner, max_attempts=3, delay_seconds=1.0, sleep=sleep)
    result = await proxy.get_data("x")
    assert result == "data-x"
    assert inner.attempts == 3
    assert delays == [1.0, 2.0]  # exponential backoff


async def test_gives_up_after_max_attempts() -> None:
    async def sleep(_: float) -> None:
        return None

    inner = _Flaky(fails_before_success=99)
    proxy = RetryingProxy(inner, max_attempts=2, delay_seconds=0.1, sleep=sleep)
    with pytest.raises(UpstreamAPIError):
        await proxy.get_data("x")
    assert inner.attempts == 2


async def test_not_found_does_not_retry() -> None:
    attempts: list[None] = []

    async def sleep(_: float) -> None:
        attempts.append(None)

    inner = _Flaky(fails_before_success=0)
    proxy = RetryingProxy(inner, max_attempts=3, delay_seconds=0.1, sleep=sleep)
    with pytest.raises(NFLNotFoundError):
        await proxy.get_missing("999")
    assert attempts == []


def test_wrapper_is_memoized_per_method_name() -> None:
    inner = _Flaky(fails_before_success=0)
    proxy = RetryingProxy(inner)
    assert proxy.get_data is proxy.get_data


async def test_season_not_available_does_not_retry() -> None:
    attempts: list[None] = []

    async def sleep(_: float) -> None:
        attempts.append(None)

    inner = _Flaky(fails_before_success=0)
    proxy = RetryingProxy(inner, max_attempts=3, delay_seconds=0.1, sleep=sleep)
    with pytest.raises(SeasonNotAvailableError):
        await proxy.get_old_season(1955)
    assert attempts == []
