"""Domain exceptions for the NFL application.

All exceptions raised by the application layer or adapters are rooted here.
Callers can catch NFLError to handle any domain-level failure, or catch
subclasses for finer-grained handling.
"""


class NFLError(Exception):
    """Base class for all NFL domain exceptions."""


class NFLNotFoundError(NFLError):
    """Raised when the requested resource does not exist (HTTP 404)."""


class UpstreamAPIError(NFLError):
    """Raised when the upstream ESPN API returns an unexpected error (non-2xx HTTP response)."""


class SeasonNotAvailableError(NFLError):
    """Raised when a requested season is outside the range of available data."""
