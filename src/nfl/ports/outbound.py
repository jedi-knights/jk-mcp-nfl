"""Outbound ports — interfaces the application layer depends on.

These are the contracts that secondary/driven adapters must satisfy. The
application layer only imports these protocols; it never references concrete
implementations. This is what makes the hexagonal boundary testable and
swap-able (e.g. real HTTP adapter vs. an in-memory stub).
"""

from typing import Protocol

from ..domain.models import (
    Athlete,
    ATSRecord,
    DefensiveEfficiency,
    EPAStats,
    GameOdds,
    Match,
    NewsItem,
    OURecord,
    PlayerInjury,
    QBAdvancedStats,
    RedZoneStats,
    SituationalRecord,
    Standing,
    SuccessRate,
    Team,
    TeamStats,
    ThirdDownStats,
    Weather,
)


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

    async def get_team_stats(self, team_id: str, season: int | None = None) -> TeamStats:
        """Return season-level stats for a team.

        Args:
            team_id: ESPN numeric team ID.
            season: Optional season year. Defaults to the current season.

        Raises:
            NFLNotFoundError: If the team has no standings entry.
        """
        ...

    async def get_team_schedule(self, team_id: str, season: int | None = None) -> list[Match]:
        """Return a team's schedule for the given season.

        Args:
            team_id: ESPN numeric team ID.
            season: Optional season year. Defaults to the current season.
        """
        ...

    async def get_roster(self, team_id: str) -> list[Athlete]:
        """Return the active roster for a team.

        Raises:
            NFLNotFoundError: If no team with that ID exists.
        """
        ...

    async def get_injuries(self, team_id: str | None = None) -> list[PlayerInjury]:
        """Return current injury report entries.

        Args:
            team_id: Optional ESPN numeric team ID. When given, filters to that
                team only. When None, returns the league-wide report.
        """
        ...

    async def get_athlete(self, athlete_id: str) -> Athlete:
        """Return a single athlete's profile.

        Raises:
            NFLNotFoundError: If no athlete with that ID exists.
        """
        ...

    async def get_news(self, team_id: str | None = None, limit: int = 10) -> list[NewsItem]:
        """Return recent NFL news items.

        Args:
            team_id: Optional ESPN numeric team ID to scope news to a team.
            limit: Maximum number of news items to return.
        """
        ...


class NFLDataPort(Protocol):
    """Contract for the upstream advanced-stats data source (nflverse).

    All methods take a populated `Team` so the data adapter can return rich
    domain types without re-fetching team metadata. The adapter only consumes
    `team.abbreviation` for joins/filters.
    """

    async def get_team_epa(self, team: Team, season: int, side: str) -> EPAStats:
        """Return EPA-per-play stats for one side of the ball."""
        ...

    async def get_success_rate(self, team: Team, season: int) -> SuccessRate:
        """Return offensive and defensive success rates for the season."""
        ...

    async def get_third_down_rate(self, team: Team, season: int) -> ThirdDownStats:
        """Return third-down conversion rates as offense and defense."""
        ...

    async def get_red_zone_efficiency(self, team: Team, season: int) -> RedZoneStats:
        """Return red zone touchdown rates as offense and defense."""
        ...

    async def get_def_points_per_100_yards(self, team: Team, season: int) -> DefensiveEfficiency:
        """Return the "Defensive Points per 100 Yards" power stat for the team."""
        ...

    async def get_qb_advanced(self, athlete_id: str, season: int) -> QBAdvancedStats:
        """Return advanced quarterback efficiency stats for a season.

        The adapter is responsible for resolving the ESPN `athlete_id` to its
        nflverse GSIS player ID via the rosters table.

        Raises:
            NFLNotFoundError: If no roster row maps to the given athlete_id.
        """
        ...

    async def get_ats_record(self, team: Team, season: int, situation: str | None = None) -> ATSRecord:
        """Return the team's against-the-spread record, optionally scoped to a situation.

        Supported `situation` values: None (overall), "home", "away",
        "favorite", "underdog", "primetime".
        """
        ...

    async def get_ou_record(self, team: Team, season: int) -> OURecord:
        """Return the team's over/under record for the season."""
        ...

    async def get_situational_record(self, team: Team, season: int, situation: str) -> SituationalRecord:
        """Return the team's SU+ATS record for a broader situational scope.

        Supported `situation` values: "vs_winning", "after_loss", "mnf", "tnf",
        "snf", "dome", "outdoor".
        """
        ...


class WeatherPort(Protocol):
    """Contract for the weather data source (Open-Meteo)."""

    async def get_weather(self, home_team_abbr: str, date_yyyymmdd: str) -> Weather:
        """Return kickoff-hour weather at the home team's stadium.

        Raises:
            NFLNotFoundError: If the team's stadium isn't known.
            ValueError: If the date string is malformed.
        """
        ...


class OddsPort(Protocol):
    """Contract for the live-odds data source (The Odds API)."""

    async def get_current_odds(self, bookmaker: str = "draftkings") -> list[GameOdds]:
        """Return current sportsbook lines for upcoming NFL games."""
        ...
