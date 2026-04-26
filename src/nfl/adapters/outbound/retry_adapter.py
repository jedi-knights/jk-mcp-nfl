"""RetryingAdapter — transparent retry decorator for NFLAPIPort.

Wraps any NFLAPIPort implementation and retries on UpstreamAPIError using
exponential backoff. NFLNotFoundError is not retried because a 404 is a
definitive answer, not a transient failure.
"""

import asyncio
import logging
from collections.abc import Callable

from ...domain.exceptions import NFLNotFoundError, UpstreamAPIError
from ...domain.models import Match, Standing, Team
from ...ports.outbound import NFLAPIPort

logger = logging.getLogger(__name__)


class RetryingAdapter:
    """Decorates a NFLAPIPort with exponential-backoff retry on UpstreamAPIError."""

    def __init__(
        self,
        inner: NFLAPIPort,
        max_attempts: int = 3,
        delay_seconds: float = 1.0,
        sleep: Callable[[float], object] = asyncio.sleep,
    ) -> None:
        """Initialize the retrying adapter.

        Args:
            inner: The NFLAPIPort implementation to wrap.
            max_attempts: Total number of attempts before giving up (minimum 1).
            delay_seconds: Base delay in seconds; doubled on each retry.
            sleep: Async callable used to wait between retries. Injectable for testing.
        """
        self._inner = inner
        self._max_attempts = max(1, max_attempts)
        self._delay_seconds = delay_seconds
        self._sleep = sleep

    async def _retry(self, method_name: str, **kwargs: object) -> object:
        """Execute a port method with retry on UpstreamAPIError.

        Raises:
            NFLNotFoundError: Immediately, without retrying.
            UpstreamAPIError: After all attempts are exhausted.
        """
        method = getattr(self._inner, method_name)
        last_error: UpstreamAPIError | None = None
        for attempt in range(self._max_attempts):
            try:
                return await method(**kwargs)
            except NFLNotFoundError:
                raise
            except UpstreamAPIError as exc:
                last_error = exc
                if attempt < self._max_attempts - 1:
                    delay = self._delay_seconds * (2**attempt)
                    logger.warning(
                        "Attempt %d/%d failed for %s, retrying in %.1fs: %s",
                        attempt + 1,
                        self._max_attempts,
                        method_name,
                        delay,
                        exc,
                    )
                    await self._sleep(delay)
        raise last_error  # type: ignore[misc]

    async def get_teams(self) -> list[Team]:
        return await self._retry("get_teams")  # type: ignore[return-value]

    async def get_team(self, team_id: str) -> Team:
        return await self._retry("get_team", team_id=team_id)  # type: ignore[return-value]

    async def get_scoreboard(self, date: str | None = None) -> list[Match]:
        return await self._retry("get_scoreboard", date=date)  # type: ignore[return-value]

    async def get_standings(self) -> list[Standing]:
        return await self._retry("get_standings")  # type: ignore[return-value]
