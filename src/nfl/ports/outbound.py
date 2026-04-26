"""Outbound ports — interfaces the application layer depends on.

These are the contracts that secondary/driven adapters must satisfy. The
application layer only imports these protocols; it never references concrete
implementations. This is what makes the hexagonal boundary testable and
swap-able (e.g. real HTTP adapter vs. an in-memory stub).
"""

from typing import Protocol

from ..domain.models import Match, Standing, Team


class NFLAPIPort(Protocol):
    """Contract for the upstream NFL data source (ESPN API)."""

    async def get_teams(self) -> list[Team]:
        """Return all active NFL teams."""
        ...

    async def get_team(self, team_id: str) -> Team:
        """Return a single team by its ESPN team ID.

        Raises:
            NFLNotFoundError: If no team with that ID exists.
        """
        ...

    async def get_scoreboard(self, date: str | None = None) -> list[Match]:
        """Return matches on the given date, or the current week if date is None.

        Args:
            date: Optional date string in YYYYMMDD format. ESPN's NFL scoreboard
                accepts a single date and returns the week containing that date.
        """
        ...

    async def get_standings(self) -> list[Standing]:
        """Return the current NFL standings, ordered by win percentage descending."""
        ...
