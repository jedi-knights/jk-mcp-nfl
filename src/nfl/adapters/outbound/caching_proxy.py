"""Generic TTL caching decorator for any async outbound port.

Unlike `CachingAdapter` (which has explicit per-method delegation for
`NFLAPIPort`), this proxy uses `__getattr__` to wrap *any* method on any
inner object with TTL caching. Useful for the analytics, weather, and odds
ports where the method surface is broader and less stable.

Method calls are intercepted and their (args, kwargs) hashed into a cache
key. Non-method attribute access falls through to the inner object.
"""

import json
import logging
import time
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


def _cache_key(method: str, args: tuple, kwargs: dict[str, Any]) -> str:
    """Build a deterministic key from a method name plus its positional and keyword args.

    Uses `default=str` so non-JSON-serializable args (e.g. domain dataclasses)
    fall back to their `repr()`, which includes all fields and is stable per
    object identity-by-value.
    """
    return json.dumps(
        {"method": method, "args": list(args), "kwargs": kwargs},
        sort_keys=True,
        default=str,
    )


class CachingProxy:
    """Wraps any async port and caches every method result for `ttl_seconds`."""

    def __init__(
        self,
        inner: object,
        ttl_seconds: float = 300.0,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._inner = inner
        self._ttl = ttl_seconds
        self._now = now
        self._cache: dict[str, tuple[float, Any]] = {}

    def __getattr__(self, name: str) -> Callable:
        """Return a coroutine-returning wrapper around the inner method.

        Raises:
            AttributeError: If the inner object has no such attribute.
        """
        attr = getattr(self._inner, name)
        if not callable(attr):
            return attr

        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            key = _cache_key(name, args, kwargs)
            entry = self._cache.get(key)
            if entry is not None and self._now() < entry[0]:
                logger.debug("CachingProxy hit: %s", name)
                return entry[1]
            result = await attr(*args, **kwargs)
            self._cache[key] = (self._now() + self._ttl, result)
            return result

        return wrapper
