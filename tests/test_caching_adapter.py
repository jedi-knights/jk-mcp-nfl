"""Tests for the caching decorator — TTL hits, misses, expiry, and per-method scoping."""

from typing import Any

from nfl.adapters.outbound.caching_adapter import CachingAdapter


class _Counter:
    def __init__(self) -> None:
        self.calls = 0

    async def get_teams(self) -> list[Any]:
        self.calls += 1
        return ["t"]

    async def get_team(self, team_id: str) -> Any:
        self.calls += 1
        return f"team-{team_id}"

    async def get_scoreboard(self, date: str | None = None) -> list[Any]:
        self.calls += 1
        return [f"sb-{date}"]

    async def get_standings(self) -> list[Any]:
        self.calls += 1
        return ["s"]


async def test_second_call_within_ttl_is_cached() -> None:
    inner = _Counter()
    cache = CachingAdapter(inner, ttl_seconds=10, now=lambda: 0.0)
    await cache.get_teams()
    await cache.get_teams()
    assert inner.calls == 1


async def test_call_after_ttl_refetches() -> None:
    inner = _Counter()
    clock = [0.0]
    cache = CachingAdapter(inner, ttl_seconds=10, now=lambda: clock[0])
    await cache.get_teams()
    clock[0] = 11.0
    await cache.get_teams()
    assert inner.calls == 2


async def test_per_method_keys_do_not_collide() -> None:
    inner = _Counter()
    cache = CachingAdapter(inner, now=lambda: 0.0)
    await cache.get_teams()
    await cache.get_standings()
    await cache.get_team("12")
    await cache.get_team("12")
    assert inner.calls == 3


async def test_scoreboard_uses_separate_ttl() -> None:
    inner = _Counter()
    clock = [0.0]
    cache = CachingAdapter(inner, ttl_seconds=300, scoreboard_ttl_seconds=30, now=lambda: clock[0])
    await cache.get_scoreboard("20260105")
    clock[0] = 35.0
    await cache.get_scoreboard("20260105")
    assert inner.calls == 2
