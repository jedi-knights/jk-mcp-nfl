"""Generic exponential-backoff retry decorator for any async outbound port.

Unlike `RetryingAdapter` (which has explicit per-method delegation for
`NFLAPIPort`), this proxy uses `__getattr__` to wrap *any* method on any
inner object with retry logic. Used by the analytics, weather, and odds
ports.

Definitive errors (`NFLNotFoundError`, `SeasonNotAvailableError`) are NOT
retried — they're answers, not transient failures. `UpstreamAPIError` IS
retried with doubling backoff.
"""

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from ...domain.exceptions import NFLNotFoundError, SeasonNotAvailableError, UpstreamAPIError

logger = logging.getLogger(__name__)


class RetryingProxy:
    """Wraps any async port with exponential-backoff retry on UpstreamAPIError.

    Wrappers are memoized so attribute access is O(1) after the first call.
    """

    def __init__(
        self,
        inner: object,
        max_attempts: int = 3,
        delay_seconds: float = 1.0,
        sleep: Callable[[float], object] = asyncio.sleep,
    ) -> None:
        self._inner = inner
        self._max_attempts = max(1, max_attempts)
        self._delay_seconds = delay_seconds
        self._sleep = sleep
        self._wrappers: dict[str, Callable] = {}

    def __getattr__(self, name: str) -> Callable:
        cached_wrapper = self._wrappers.get(name)
        if cached_wrapper is not None:
            return cached_wrapper
        attr = getattr(self._inner, name)
        if not callable(attr):
            return attr
        wrapper = self._build_wrapper(name, attr)
        self._wrappers[name] = wrapper
        return wrapper

    def _build_wrapper(self, name: str, attr: Callable) -> Callable:
        """Construct the per-method async wrapper that retries on UpstreamAPIError."""

        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_error: UpstreamAPIError | None = None
            for attempt in range(self._max_attempts):
                try:
                    return await attr(*args, **kwargs)
                except (NFLNotFoundError, SeasonNotAvailableError):
                    raise
                except UpstreamAPIError as exc:
                    last_error = exc
                    if attempt < self._max_attempts - 1:
                        delay = self._delay_seconds * (2**attempt)
                        logger.warning(
                            "RetryingProxy attempt %d/%d failed for %s, retrying in %.1fs: %s",
                            attempt + 1,
                            self._max_attempts,
                            name,
                            delay,
                            exc,
                        )
                        await self._sleep(delay)
            raise last_error  # type: ignore[misc]

        return wrapper
