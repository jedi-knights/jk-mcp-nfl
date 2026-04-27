"""Application service — the core of the hexagonal architecture.

This layer orchestrates work by delegating to outbound ports. It knows nothing
about MCP, HTTP, or JSON — those are adapter concerns.
"""

from datetime import UTC, datetime

from ..domain.models import (
    Athlete,
    ATSRecord,
    DefensiveEfficiency,
    EPAStats,
    GameOdds,
    HeadToHead,
    Match,
    MatchCompetitor,
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
from ..ports.outbound import NFLAPIPort, NFLDataPort, OddsPort, WeatherPort

_MIN_SEASON = 1970
_H2H_LOOKBACK_YEARS = 5
_MAX_NEWS_LIMIT = 50
_ATS_SITUATIONS = frozenset({"home", "away", "favorite", "underdog", "primetime"})
_SITUATIONAL_OPTIONS = frozenset({"vs_winning", "after_loss", "mnf", "tnf", "snf", "dome", "outdoor"})


def _validate_yyyymmdd(value: str, name: str) -> str:
    """Normalize and validate a YYYYMMDD date string.

    Raises:
        ValueError: If the value isn't 8 digits.
    """
    stripped = value.strip()
    if len(stripped) != 8 or not stripped.isdigit():
        raise ValueError(f"{name} must be in YYYYMMDD format (got {value!r})")
    return stripped


def _require_team_id(team_id: str, name: str = "team_id") -> str:
    """Strip and require a non-empty team identifier."""
    if not team_id or not team_id.strip():
        raise ValueError(f"{name} must not be empty")
    return team_id.strip()


def _validate_season(season: int | None) -> int | None:
    """Reject obviously bogus season years; pass through None."""
    if season is None:
        return None
    if season < _MIN_SEASON:
        raise ValueError(f"season must be {_MIN_SEASON} or later (got {season})")
    return season


def _current_season() -> int:
    """Return the NFL season year named after its September start."""
    today = datetime.now(UTC)
    return today.year if today.month >= 8 else today.year - 1


def _h2h_seasons() -> range:
    """Iterate the seasons to walk for a head-to-head query, most recent first."""
    current = _current_season()
    return range(current, current - _H2H_LOOKBACK_YEARS, -1)


def _competitor_for(match: Match, team_id: str) -> MatchCompetitor | None:
    """Return the competitor entry for a given team in a match, or None."""
    for c in match.competitors:
        if c.team.id == team_id:
            return c
    return None


def _filter_h2h(matches: list[Match], opponent_id: str) -> list[Match]:
    """Keep only matches that include `opponent_id`, sorted by date desc."""
    relevant = [m for m in matches if _competitor_for(m, opponent_id) is not None]
    return sorted(relevant, key=lambda m: m.date, reverse=True)


def _count_h2h(matches: list[Match], team_a: str, team_b: str) -> tuple[int, int, int]:
    """Tally (a_wins, b_wins, ties) across the matches."""
    a = b = t = 0
    for m in matches:
        winner = next((c.team.id for c in m.competitors if c.winner is True), None)
        if winner == team_a:
            a += 1
        elif winner == team_b:
            b += 1
        else:
            t += 1
    return a, b, t


def _team_from(match: Match, team_id: str) -> Team | None:
    """Return the Team object for the given ID in this match, or None."""
    competitor = _competitor_for(match, team_id)
    return competitor.team if competitor else None


def _identify_h2h_teams(matches: list[Match], team_a: str, team_b: str) -> tuple[Team | None, Team | None]:
    """Find the Team objects for both IDs by scanning the matches."""
    a_team = b_team = None
    for m in matches:
        a_team = a_team or _team_from(m, team_a)
        b_team = b_team or _team_from(m, team_b)
        if a_team and b_team:
            break
    return a_team, b_team


class NFLService:
    """Coordinates NFL data lookups through the outbound ports.

    Two driven ports are injected:
      - `repo`: the ESPN-backed league feed (teams, scoreboard, standings, etc.)
      - `data_repo`: the nflverse-backed advanced-stats feed (EPA, red zone, etc.)

    `data_repo` is optional so the service can be wired without nflverse during
    early bootstrap; analytics tools then raise a clear error if invoked.
    """

    def __init__(
        self,
        repo: NFLAPIPort,
        data_repo: NFLDataPort | None = None,
        weather_repo: WeatherPort | None = None,
        odds_repo: OddsPort | None = None,
    ) -> None:
        self._repo = repo
        self._data_repo = data_repo
        self._weather_repo = weather_repo
        self._odds_repo = odds_repo

    def _require_data_repo(self) -> NFLDataPort:
        if self._data_repo is None:
            raise RuntimeError("Advanced stats are unavailable: NFLDataPort not configured.")
        return self._data_repo

    def _require_weather_repo(self) -> WeatherPort:
        if self._weather_repo is None:
            raise RuntimeError("Weather is unavailable: WeatherPort not configured.")
        return self._weather_repo

    def _require_odds_repo(self) -> OddsPort:
        if self._odds_repo is None:
            raise RuntimeError("Live odds are unavailable: ODDS_API_KEY not configured.")
        return self._odds_repo

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

    async def get_team_stats(self, team_id: str, season: int | None = None) -> TeamStats:
        """Return season-level stats for a team.

        Args:
            team_id: ESPN numeric team ID.
            season: Optional season year. Defaults to the current season.

        Raises:
            ValueError: If team_id is blank or season is implausibly old.
            NFLNotFoundError: If the team has no stats entry for the season.
        """
        return await self._repo.get_team_stats(_require_team_id(team_id), _validate_season(season))

    async def get_team_schedule(self, team_id: str, season: int | None = None) -> list[Match]:
        """Return a team's schedule for the given season.

        Args:
            team_id: ESPN numeric team ID.
            season: Optional season year. Defaults to the current season.

        Raises:
            ValueError: If team_id is blank or season is implausibly old.
        """
        return await self._repo.get_team_schedule(_require_team_id(team_id), _validate_season(season))

    async def get_head_to_head(self, team_a: str, team_b: str, last_n: int = 5) -> HeadToHead:
        """Return the head-to-head record between two teams across recent seasons.

        Walks `team_a`'s schedule for each of the most recent seasons (up to
        `_H2H_LOOKBACK_YEARS`), filters to games involving `team_b`, and
        returns up to `last_n` matchups ordered most-recent first.

        Args:
            team_a: ESPN numeric team ID for the first team.
            team_b: ESPN numeric team ID for the second team.
            last_n: Maximum number of completed matchups to include.

        Raises:
            ValueError: If the two team IDs are equal or last_n is non-positive.
        """
        a = _require_team_id(team_a, "team_a")
        b = _require_team_id(team_b, "team_b")
        if a == b:
            raise ValueError("team_a and team_b must differ")
        if last_n <= 0:
            raise ValueError(f"last_n must be positive (got {last_n})")
        matches = await self._collect_h2h_matches(a, b, last_n)
        a_team, b_team = _identify_h2h_teams(matches, a, b)
        if a_team is None:
            a_team = await self._repo.get_team(a)
        if b_team is None:
            b_team = await self._repo.get_team(b)
        a_w, b_w, t = _count_h2h(matches, a, b)
        return HeadToHead(team_a=a_team, team_b=b_team, team_a_wins=a_w, team_b_wins=b_w, ties=t, matches=matches)

    async def get_roster(self, team_id: str) -> list[Athlete]:
        """Return the active roster for a team.

        Raises:
            ValueError: If team_id is blank.
            NFLNotFoundError: If no team with that ID exists.
        """
        return await self._repo.get_roster(_require_team_id(team_id))

    async def get_injuries(self, team_id: str | None = None) -> list[PlayerInjury]:
        """Return the current NFL injury report, optionally scoped to one team.

        Args:
            team_id: Optional ESPN numeric team ID. When None, returns the
                league-wide injury report.

        Raises:
            ValueError: If team_id is the empty string (use None to skip).
        """
        scope = _require_team_id(team_id) if team_id is not None else None
        return await self._repo.get_injuries(scope)

    async def get_athlete(self, athlete_id: str) -> Athlete:
        """Return a single athlete's profile.

        Raises:
            ValueError: If athlete_id is blank.
            NFLNotFoundError: If no athlete with that ID exists.
        """
        return await self._repo.get_athlete(_require_team_id(athlete_id, "athlete_id"))

    async def get_news(self, team_id: str | None = None, limit: int = 10) -> list[NewsItem]:
        """Return recent NFL news items.

        Args:
            team_id: Optional ESPN numeric team ID to scope news to a team.
            limit: Maximum number of items to return; capped at MAX_NEWS_LIMIT.

        Raises:
            ValueError: If limit is non-positive.
        """
        if limit <= 0:
            raise ValueError(f"limit must be positive (got {limit})")
        scope = _require_team_id(team_id) if team_id is not None else None
        return await self._repo.get_news(scope, min(limit, _MAX_NEWS_LIMIT))

    async def get_team_epa(self, team_id: str, season: int | None = None, side: str = "offense") -> EPAStats:
        """Return EPA-per-play stats for one side of the ball.

        Args:
            team_id: ESPN numeric team ID.
            season: Optional season year. Defaults to the current season.
            side: "offense" or "defense".

        Raises:
            ValueError: If team_id is blank, season is implausible, or side is invalid.
            NFLNotFoundError: If the team ID is unknown.
            RuntimeError: If the advanced-stats port isn't configured.
        """
        if side not in ("offense", "defense"):
            raise ValueError(f"side must be 'offense' or 'defense' (got {side!r})")
        team, year = await self._resolve_team_and_season(team_id, season)
        return await self._require_data_repo().get_team_epa(team, year, side)

    async def get_success_rate(self, team_id: str, season: int | None = None) -> SuccessRate:
        """Return offensive and defensive success rates for the season.

        Raises:
            ValueError: If team_id is blank or season is implausible.
            NFLNotFoundError: If the team ID is unknown.
            RuntimeError: If the advanced-stats port isn't configured.
        """
        team, year = await self._resolve_team_and_season(team_id, season)
        return await self._require_data_repo().get_success_rate(team, year)

    async def get_third_down_rate(self, team_id: str, season: int | None = None) -> ThirdDownStats:
        """Return third-down conversion rates as offense and defense."""
        team, year = await self._resolve_team_and_season(team_id, season)
        return await self._require_data_repo().get_third_down_rate(team, year)

    async def get_red_zone_efficiency(self, team_id: str, season: int | None = None) -> RedZoneStats:
        """Return red zone touchdown rates as offense and defense."""
        team, year = await self._resolve_team_and_season(team_id, season)
        return await self._require_data_repo().get_red_zone_efficiency(team, year)

    async def get_def_points_per_100_yards(self, team_id: str, season: int | None = None) -> DefensiveEfficiency:
        """Return the "Defensive Points per 100 Yards" power stat for a team."""
        team, year = await self._resolve_team_and_season(team_id, season)
        return await self._require_data_repo().get_def_points_per_100_yards(team, year)

    async def get_ats_record(self, team_id: str, season: int | None = None, situation: str | None = None) -> ATSRecord:
        """Return the team's ATS record for a season, optionally scoped to a situation.

        Args:
            team_id: ESPN numeric team ID.
            season: Optional season year.
            situation: One of "home", "away", "favorite", "underdog", "primetime".
                When None, returns the overall ATS record.

        Raises:
            ValueError: If situation is not in the supported set.
        """
        if situation is not None and situation not in _ATS_SITUATIONS:
            raise ValueError(f"situation must be one of {sorted(_ATS_SITUATIONS)} or None (got {situation!r})")
        team, year = await self._resolve_team_and_season(team_id, season)
        return await self._require_data_repo().get_ats_record(team, year, situation)

    async def get_ou_record(self, team_id: str, season: int | None = None) -> OURecord:
        """Return the team's over/under record for a season."""
        team, year = await self._resolve_team_and_season(team_id, season)
        return await self._require_data_repo().get_ou_record(team, year)

    async def get_situational_record(
        self, team_id: str, situation: str, season: int | None = None
    ) -> SituationalRecord:
        """Return SU+ATS records for a team in a broader situational scope.

        Args:
            team_id: ESPN numeric team ID.
            situation: One of "vs_winning", "after_loss", "mnf", "tnf",
                "snf", "dome", "outdoor".
            season: Optional season year.

        Raises:
            ValueError: If situation is not in the supported set.
        """
        if situation not in _SITUATIONAL_OPTIONS:
            raise ValueError(f"situation must be one of {sorted(_SITUATIONAL_OPTIONS)} (got {situation!r})")
        team, year = await self._resolve_team_and_season(team_id, season)
        return await self._require_data_repo().get_situational_record(team, year, situation)

    async def get_current_odds(self, bookmaker: str = "draftkings") -> list[GameOdds]:
        """Return current sportsbook lines for upcoming NFL games.

        Args:
            bookmaker: The Odds API bookmaker key (default "draftkings").

        Raises:
            RuntimeError: If the Odds API port isn't configured (no API key).
        """
        return await self._require_odds_repo().get_current_odds(bookmaker)

    async def get_game_weather(self, home_team_id: str, date: str) -> Weather:
        """Return kickoff-hour weather for the home team's stadium on a date.

        Args:
            home_team_id: ESPN numeric team ID for the HOME team.
            date: Game date in YYYYMMDD format.

        Raises:
            ValueError: If team_id is blank or date is malformed.
            NFLNotFoundError: If the team or its stadium isn't known.
            RuntimeError: If the weather port isn't configured.
        """
        validated_id = _require_team_id(home_team_id, "home_team_id")
        validated_date = _validate_yyyymmdd(date, "date")
        team = await self._repo.get_team(validated_id)
        return await self._require_weather_repo().get_weather(team.abbreviation, validated_date)

    async def get_qb_advanced(self, athlete_id: str, season: int | None = None) -> QBAdvancedStats:
        """Return advanced quarterback efficiency stats for a season.

        Args:
            athlete_id: ESPN numeric athlete ID.
            season: Optional season year. Defaults to the current season.

        Raises:
            ValueError: If athlete_id is blank or season is implausibly old.
            NFLNotFoundError: If the athlete can't be mapped to a nflverse player.
            RuntimeError: If the advanced-stats port isn't configured.
        """
        validated_id = _require_team_id(athlete_id, "athlete_id")
        year = _validate_season(season) or _current_season()
        return await self._require_data_repo().get_qb_advanced(validated_id, year)

    async def _resolve_team_and_season(self, team_id: str, season: int | None) -> tuple[Team, int]:
        """Validate inputs and resolve team_id → Team plus a concrete season year."""
        validated_id = _require_team_id(team_id)
        validated_season = _validate_season(season)
        team = await self._repo.get_team(validated_id)
        return team, validated_season if validated_season is not None else _current_season()

    async def _collect_h2h_matches(self, team_a: str, team_b: str, last_n: int) -> list[Match]:
        """Walk seasons backward, accumulating up to `last_n` matchups vs team_b.

        De-duplicates by match ID so a duplicate upstream response can't
        double-count a single matchup.
        """
        collected: list[Match] = []
        seen: set[str] = set()
        for season in _h2h_seasons():
            schedule = await self._repo.get_team_schedule(team_a, season)
            for m in _filter_h2h(schedule, team_b):
                if m.id in seen:
                    continue
                seen.add(m.id)
                collected.append(m)
                if len(collected) >= last_n:
                    return collected
        return collected
