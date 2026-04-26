"""Application service — the core of the hexagonal architecture.

This layer orchestrates work by delegating to outbound ports. It knows nothing
about MCP, HTTP, or JSON — those are adapter concerns.
"""

from ..domain.models import Match, Standing, Team
from ..ports.outbound import NFLAPIPort


def _validate_yyyymmdd(value: str, name: str) -> str:
    """Normalize and validate a YYYYMMDD date string.

    Raises:
        ValueError: If the value isn't 8 digits.
    """
    stripped = value.strip()
    if len(stripped) != 8 or not stripped.isdigit():
        raise ValueError(f"{name} must be in YYYYMMDD format (got {value!r})")
    return stripped


class NFLService:
    """Coordinates NFL data lookups through the outbound port.

    A single driven port is injected: the ESPN-backed `repo` (read-only league
    feeds). Additional sources (player stats, news, etc.) can be added as
    further ports without touching this class's existing methods.
    """

    def __init__(self, repo: NFLAPIPort) -> None:
        self._repo = repo

    async def get_teams(self) -> list[Team]:
        """Return all active NFL teams."""
        return await self._repo.get_teams()

    async def get_team(self, team_id: str) -> Team:
        """Return a single team by its ESPN team ID.

        Raises:
            ValueError: If team_id is empty.
            NFLNotFoundError: If no team with that ID exists.
        """
        if not team_id or not team_id.strip():
            raise ValueError("team_id must not be empty")
        return await self._repo.get_team(team_id.strip())

    async def get_scoreboard(self, date: str | None = None) -> list[Match]:
        """Return matches for a date, or the current week if date is None.

        Args:
            date: Optional date string in YYYYMMDD format.

        Raises:
            ValueError: If date is malformed.
        """
        if date is not None:
            date = _validate_yyyymmdd(date, "date")
        return await self._repo.get_scoreboard(date)

    async def get_standings(self) -> list[Standing]:
        """Return the current NFL standings ordered by win percentage descending."""
        return await self._repo.get_standings()
