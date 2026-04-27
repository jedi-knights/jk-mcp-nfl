"""Tests for the generic CachingProxy — works on any async port."""

from typing import Any

import pytest

from nfl.adapters.outbound.caching_proxy import CachingProxy


class _FakePort:
    def __init__(self) -> None:
        self.calls = 0

    async def get_thing(self, key: str) -> str:
        self.calls += 1
        return f"thing-{key}-{self.calls}"

    async def get_other(self) -> int:
        self.calls += 1
        return self.calls

    instance_attr = "static-value"


async def test_repeat_call_within_ttl_is_cached() -> None:
    inner = _FakePort()
    proxy = CachingProxy(inner, ttl_seconds=10, now=lambda: 0.0)
    a = await proxy.get_thing("x")
    b = await proxy.get_thing("x")
    assert a == b == "thing-x-1"
    assert inner.calls == 1


async def test_call_after_ttl_refetches() -> None:
    inner = _FakePort()
    clock = [0.0]
    proxy = CachingProxy(inner, ttl_seconds=10, now=lambda: clock[0])
    await proxy.get_thing("x")
    clock[0] = 11.0
    await proxy.get_thing("x")
    assert inner.calls == 2


async def test_different_methods_use_separate_cache_keys() -> None:
    inner = _FakePort()
    proxy = CachingProxy(inner, ttl_seconds=10, now=lambda: 0.0)
    await proxy.get_thing("x")
    await proxy.get_other()
    await proxy.get_thing("x")
    await proxy.get_other()
    assert inner.calls == 2


async def test_positional_and_keyword_args_share_no_collision() -> None:
    inner = _FakePort()
    proxy = CachingProxy(inner, ttl_seconds=10, now=lambda: 0.0)
    await proxy.get_thing("a")
    await proxy.get_thing("b")
    await proxy.get_thing(key="c")
    assert inner.calls == 3


async def test_proxy_caches_dataclass_args_by_repr() -> None:
    """Domain dataclasses passed as args still produce stable cache keys."""
    from dataclasses import dataclass

    @dataclass
    class _Thing:
        id: str

    class _PortWithDataclass:
        def __init__(self) -> None:
            self.calls = 0

        async def get_thing(self, t: Any) -> str:
            self.calls += 1
            return t.id

    inner = _PortWithDataclass()
    proxy = CachingProxy(inner, ttl_seconds=10, now=lambda: 0.0)
    await proxy.get_thing(_Thing("abc"))
    await proxy.get_thing(_Thing("abc"))
    assert inner.calls == 1


def test_non_callable_attributes_pass_through() -> None:
    inner = _FakePort()
    proxy = CachingProxy(inner)
    assert proxy.instance_attr == "static-value"


def test_missing_attribute_raises() -> None:
    inner = _FakePort()
    proxy = CachingProxy(inner)
    with pytest.raises(AttributeError):
        proxy.does_not_exist  # noqa: B018
