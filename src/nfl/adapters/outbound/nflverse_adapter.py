"""Outbound adapter — fetches NFL play-by-play, schedules, and rosters from nflverse.

The nflverse-data project (github.com/nflverse) publishes per-season parquet
files as GitHub Release artifacts. This adapter:

1. Resolves the artifact URL for a given dataset+season
2. Caches the file on disk under `cache_dir`
3. Reads the parquet into a polars DataFrame for downstream analytics

Caching policy:
- Past seasons are final — once cached, they're never re-downloaded.
- Current-season files are re-downloaded if older than `max_age_hours`.

This adapter does not expose any port methods directly. The analytical tools
(EPA, success rate, ATS records, etc.) are added by higher-tier tasks and call
into the load methods here. Keeping this adapter free of port surface keeps
the polars dependency contained until a use-case actually needs it.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx
import polars as pl

from ...domain.exceptions import NFLNotFoundError, SeasonNotAvailableError, UpstreamAPIError
from ...domain.models import (
    ATSRecord,
    DefensiveEfficiency,
    EPAStats,
    OURecord,
    QBAdvancedStats,
    RedZoneStats,
    SituationalRecord,
    SuccessRate,
    Team,
    ThirdDownStats,
)

logger = logging.getLogger(__name__)

_RELEASE_BASE_URL = "https://github.com/nflverse/nflverse-data/releases/download"
_DEFAULT_TIMEOUT = 120.0  # parquet downloads can be tens of MB


@dataclass(frozen=True)
class _Dataset:
    """Static config for a single nflverse dataset.

    `per_season` is False for datasets that ship one file containing all
    seasons (e.g. schedules); the season argument then becomes a filter
    applied after loading.
    """

    tag: str
    filename_template: str
    per_season: bool


_PBP = _Dataset(tag="pbp", filename_template="play_by_play_{season}.parquet", per_season=True)
_SCHEDULES = _Dataset(tag="schedules", filename_template="games.parquet", per_season=False)
_ROSTERS = _Dataset(tag="rosters", filename_template="roster_{season}.parquet", per_season=True)


def _utc_now() -> datetime:
    """Wall-clock helper, isolated for test injection."""
    return datetime.now(UTC)


def _current_season(now: datetime) -> int:
    """Return the NFL season year (named after its September start)."""
    return now.year if now.month >= 8 else now.year - 1


class NFLVerseAdapter:
    """Downloads, caches, and loads nflverse parquet artifacts."""

    def __init__(
        self,
        cache_dir: Path | str,
        client: httpx.AsyncClient | None = None,
        max_age_hours: float = 24.0,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        """Initialize the adapter.

        Args:
            cache_dir: Directory on disk for cached parquet files. Created if missing.
            client: Optional httpx.AsyncClient. Inject a MockTransport in tests.
            max_age_hours: Refresh interval for current-season cached files.
            now: Wall-clock callable (UTC). Injectable for testing.
        """
        self._cache_dir = Path(cache_dir)
        self._client = client or httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT, follow_redirects=True)
        self._max_age_hours = max_age_hours
        self._now = now
        # In-memory cache so multiple analytics on the same season don't re-parse
        # the same parquet file. Keyed by (dataset_tag, season).
        self._df_cache: dict[tuple[str, int], pl.DataFrame] = {}

    async def load_play_by_play(self, season: int) -> pl.DataFrame:
        """Return the play-by-play parquet for a season as a polars DataFrame."""
        return await self._load_cached(_PBP, season)

    async def load_schedules(self, season: int | None = None) -> pl.DataFrame:
        """Return the schedules parquet, optionally filtered to a single season.

        nflverse ships schedules as one file containing every season. The
        `season` argument filters in-process after the load.
        """
        anchor_season = season if season is not None else _current_season(self._now())
        df = await self._load_cached(_SCHEDULES, anchor_season)
        return df.filter(pl.col("season") == season) if season is not None else df

    async def load_rosters(self, season: int) -> pl.DataFrame:
        """Return the rosters parquet for a season as a polars DataFrame."""
        return await self._load_cached(_ROSTERS, season)

    async def _load_cached(self, dataset: _Dataset, season: int) -> pl.DataFrame:
        """Return a cached DataFrame for (dataset, season), parsing parquet on miss."""
        key = (dataset.tag, season)
        cached = self._df_cache.get(key)
        if cached is not None:
            return cached
        path = await self._ensure_cached(dataset, season)
        df = pl.read_parquet(path)
        self._df_cache[key] = df
        return df

    # ----- NFLDataPort analytical methods (consumed by NFLService) -----

    async def get_team_epa(self, team: Team, season: int, side: str) -> EPAStats:
        """Compute EPA-per-play stats for one side of the ball for a team."""
        pbp = await self.load_play_by_play(season)
        team_col = "posteam" if side == "offense" else "defteam"
        plays = pbp.filter(pl.col(team_col) == team.abbreviation)
        return _compute_epa(team, season, side, plays)

    async def get_success_rate(self, team: Team, season: int) -> SuccessRate:
        """Compute offense + defense success rate for a team in a season."""
        pbp = await self.load_play_by_play(season)
        return _compute_success_rate(team, season, pbp)

    async def get_third_down_rate(self, team: Team, season: int) -> ThirdDownStats:
        """Compute offense + defense third-down conversion rate for a team."""
        pbp = await self.load_play_by_play(season)
        return _compute_third_down(team, season, pbp)

    async def get_red_zone_efficiency(self, team: Team, season: int) -> RedZoneStats:
        """Compute offense + defense red-zone TD rate for a team."""
        pbp = await self.load_play_by_play(season)
        return _compute_red_zone(team, season, pbp)

    async def get_def_points_per_100_yards(self, team: Team, season: int) -> DefensiveEfficiency:
        """Compute the "Defensive Points per 100 Yards" power stat for a team.

        Yards allowed comes from pbp (sum of yards_gained where defteam=team);
        points allowed comes from schedules (the team's opponents' scores).
        """
        pbp = await self.load_play_by_play(season)
        schedules = await self.load_schedules(season)
        return _compute_def_points_per_100(team, season, pbp, schedules)

    async def get_qb_advanced(self, athlete_id: str, season: int) -> QBAdvancedStats:
        """Compute advanced QB stats for the season by joining rosters → pbp."""
        rosters = await self.load_rosters(season)
        gsis_id, name = _resolve_player(rosters, athlete_id)
        pbp = await self.load_play_by_play(season)
        return _compute_qb_advanced(athlete_id, name, season, gsis_id, pbp)

    async def get_ats_record(self, team: Team, season: int, situation: str | None = None) -> ATSRecord:
        """Compute the team's ATS record for the season, optionally scoped to a situation."""
        schedules = await self.load_schedules(season)
        return _compute_ats(team, season, situation, schedules)

    async def get_ou_record(self, team: Team, season: int) -> OURecord:
        """Compute the team's over/under record for the season."""
        schedules = await self.load_schedules(season)
        return _compute_ou(team, season, schedules)

    async def get_situational_record(self, team: Team, season: int, situation: str) -> SituationalRecord:
        """Compute SU + ATS records for a team within a broader situational scope."""
        schedules = await self.load_schedules(season)
        return _compute_situational(team, season, situation, schedules)

    async def _ensure_cached(self, dataset: _Dataset, season: int) -> Path:
        """Return the cached file path, downloading if missing or stale."""
        path = self._cache_path(dataset, season)
        if not self._is_stale(path, season):
            logger.debug("nflverse cache hit: %s", path)
            return path
        await self._download(dataset, season, path)
        return path

    def _cache_path(self, dataset: _Dataset, season: int) -> Path:
        filename = dataset.filename_template.format(season=season) if dataset.per_season else dataset.filename_template
        return self._cache_dir / dataset.tag / filename

    def _url(self, dataset: _Dataset, season: int) -> str:
        filename = dataset.filename_template.format(season=season) if dataset.per_season else dataset.filename_template
        return f"{_RELEASE_BASE_URL}/{dataset.tag}/{filename}"

    def _is_stale(self, path: Path, season: int) -> bool:
        """A file is stale if missing, or if it's from the current season and too old."""
        if not path.exists():
            return True
        if season < _current_season(self._now()):
            return False
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        age_hours = (self._now() - mtime).total_seconds() / 3600.0
        return age_hours > self._max_age_hours

    async def _download(self, dataset: _Dataset, season: int, target: Path) -> None:
        """Fetch the artifact and atomically write it to `target`."""
        url = self._url(dataset, season)
        logger.info("nflverse download: %s", url)
        response = await self._client.get(url)
        _check_response(response, dataset, season, url)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(response.content)


def _check_response(response: httpx.Response, dataset: _Dataset, season: int, url: str) -> None:
    """Translate non-2xx HTTP responses into domain exceptions."""
    if response.status_code == 404:
        raise SeasonNotAvailableError(f"nflverse {dataset.tag} not available for season {season}: {url}")
    if response.status_code >= 400:
        raise UpstreamAPIError(f"nflverse upstream error {response.status_code}: {url}")


# ---------- Pure analytical helpers (testable in isolation) ----------


def _safe_mean(series: pl.Series) -> float:
    """Mean of a polars Series, returning 0.0 for empty input."""
    if series.is_empty():
        return 0.0
    value = series.mean()
    return float(value) if value is not None else 0.0


def _compute_epa(team: Team, season: int, side: str, plays: pl.DataFrame) -> EPAStats:
    """Build an EPAStats from a pre-filtered plays DataFrame for one side."""
    epa = plays["epa"] if "epa" in plays.columns else pl.Series("epa", [], dtype=pl.Float64)
    pass_plays = plays.filter(pl.col("pass") == 1)["epa"] if "pass" in plays.columns else epa.head(0)
    rush_plays = plays.filter(pl.col("rush") == 1)["epa"] if "rush" in plays.columns else epa.head(0)
    success = plays["success"] if "success" in plays.columns else epa.head(0)
    return EPAStats(
        team=team,
        season=season,
        side=side,
        epa_per_play=_safe_mean(epa),
        pass_epa_per_play=_safe_mean(pass_plays),
        rush_epa_per_play=_safe_mean(rush_plays),
        success_rate=_safe_mean(success),
    )


def _compute_success_rate(team: Team, season: int, pbp: pl.DataFrame) -> SuccessRate:
    """Build a SuccessRate row from a season's pbp DataFrame."""
    off = pbp.filter(pl.col("posteam") == team.abbreviation)
    def_ = pbp.filter(pl.col("defteam") == team.abbreviation)
    return SuccessRate(
        team=team,
        season=season,
        rate_offense=_safe_mean(off["success"]) if "success" in off.columns else 0.0,
        rate_defense=_safe_mean(def_["success"]) if "success" in def_.columns else 0.0,
        plays_offense=off.height,
        plays_defense=def_.height,
    )


def _compute_third_down(team: Team, season: int, pbp: pl.DataFrame) -> ThirdDownStats:
    """Build a ThirdDownStats row from a season's pbp DataFrame."""
    third = pbp.filter(pl.col("down") == 3) if "down" in pbp.columns else pbp.head(0)
    off = third.filter(pl.col("posteam") == team.abbreviation)
    def_ = third.filter(pl.col("defteam") == team.abbreviation)
    off_attempts = off.height
    off_conv = int(off["third_down_converted"].sum()) if "third_down_converted" in off.columns else 0
    def_attempts = def_.height
    def_conv = int(def_["third_down_converted"].sum()) if "third_down_converted" in def_.columns else 0
    return ThirdDownStats(
        team=team,
        season=season,
        attempts_offense=off_attempts,
        conversions_offense=off_conv,
        rate_offense=(off_conv / off_attempts) if off_attempts else 0.0,
        attempts_defense=def_attempts,
        conversions_defense_allowed=def_conv,
        rate_defense=(def_conv / def_attempts) if def_attempts else 0.0,
    )


def _compute_red_zone(team: Team, season: int, pbp: pl.DataFrame) -> RedZoneStats:
    """Build a RedZoneStats row using one row per (game_id, drive) red-zone trip."""
    if "yardline_100" not in pbp.columns:
        return RedZoneStats(
            team=team,
            season=season,
            trips_offense=0,
            touchdowns_offense=0,
            td_rate_offense=0.0,
            trips_defense=0,
            touchdowns_defense_allowed=0,
            td_rate_defense=0.0,
        )
    rz = pbp.filter(pl.col("yardline_100") <= 20)
    off_trips, off_tds = _red_zone_trips(rz, "posteam", team.abbreviation)
    def_trips, def_tds = _red_zone_trips(rz, "defteam", team.abbreviation)
    return RedZoneStats(
        team=team,
        season=season,
        trips_offense=off_trips,
        touchdowns_offense=off_tds,
        td_rate_offense=(off_tds / off_trips) if off_trips else 0.0,
        trips_defense=def_trips,
        touchdowns_defense_allowed=def_tds,
        td_rate_defense=(def_tds / def_trips) if def_trips else 0.0,
    )


def _red_zone_trips(rz: pl.DataFrame, team_col: str, team_abbr: str) -> tuple[int, int]:
    """Count distinct red-zone trips and how many ended in an offensive touchdown.

    Uses `pass_touchdown` + `rush_touchdown` so defensive scores (pick-6,
    fumble-6) on the same play don't get attributed to the offense's red-zone
    success rate. Falls back to the generic `touchdown` flag if the more
    specific columns are absent.
    """
    side = rz.filter(pl.col(team_col) == team_abbr)
    if side.is_empty():
        return 0, 0
    td_expr = _offensive_td_expr(side.columns)
    grouped = side.group_by(["game_id", "drive"]).agg(td_expr.max().alias("td"))
    trips = grouped.height
    tds = int(grouped["td"].sum())
    return trips, tds


def _offensive_td_expr(columns: list[str]) -> pl.Expr:
    """Per-play offensive-TD indicator: pass_td OR rush_td, falling back to touchdown."""
    if "pass_touchdown" in columns and "rush_touchdown" in columns:
        return (pl.col("pass_touchdown") + pl.col("rush_touchdown")).clip(0, 1)
    return pl.col("touchdown")


def _compute_def_points_per_100(
    team: Team, season: int, pbp: pl.DataFrame, schedules: pl.DataFrame
) -> DefensiveEfficiency:
    """Build a DefensiveEfficiency row using points-against (schedules) and yards-against (pbp).

    Metric is points allowed per 100 yards of defense, i.e.
    `points_allowed / (yards_allowed / 100)`. Lower is better. The bands cited
    by sportsbettingstats.com: <6.0 "good", 6.0-7.0 "average", >7.0 "poor".
    """
    yards_allowed = _yards_allowed(team.abbreviation, pbp)
    points_allowed = _points_allowed(team.abbreviation, schedules)
    metric = points_allowed / (yards_allowed / 100.0) if yards_allowed > 0 else 0.0
    return DefensiveEfficiency(
        team=team,
        season=season,
        yards_allowed=yards_allowed,
        points_allowed=points_allowed,
        points_per_100_yards=metric,
        rating=_def_rating(metric),
    )


def _yards_allowed(team_abbr: str, pbp: pl.DataFrame) -> int:
    if "yards_gained" not in pbp.columns:
        return 0
    series = pbp.filter(pl.col("defteam") == team_abbr)["yards_gained"]
    return int(series.sum() or 0)


def _points_allowed(team_abbr: str, schedules: pl.DataFrame) -> int:
    """Sum points scored by the team's opponents across the season."""
    home = schedules.filter(pl.col("home_team") == team_abbr)
    away = schedules.filter(pl.col("away_team") == team_abbr)
    home_against = int(home["away_score"].sum() or 0) if "away_score" in home.columns else 0
    away_against = int(away["home_score"].sum() or 0) if "home_score" in away.columns else 0
    return home_against + away_against


def _def_rating(metric: float) -> str:
    """Bucket the DEF pts/100 yds power stat per the sportsbettingstats thresholds."""
    if metric == 0.0:
        return "unknown"
    if metric < 6.0:
        return "good"
    if metric > 7.0:
        return "poor"
    return "average"


def _resolve_player(rosters: pl.DataFrame, espn_athlete_id: str) -> tuple[str, str]:
    """Look up a player's nflverse GSIS id + display name by ESPN athlete id.

    Raises:
        NFLNotFoundError: If the rosters table doesn't carry the espn_id column
            or no row matches.
    """
    if "espn_id" not in rosters.columns:
        raise NFLNotFoundError(f"Rosters table has no espn_id column for athlete {espn_athlete_id}")
    espn_col = rosters["espn_id"].cast(pl.Utf8)
    matches = rosters.filter(espn_col == espn_athlete_id)
    if matches.is_empty():
        raise NFLNotFoundError(f"No nflverse roster entry maps to ESPN athlete {espn_athlete_id}")
    row = matches.row(0, named=True)
    return str(row.get("gsis_id", "")), str(row.get("full_name", ""))


def _col_int_sum(df: pl.DataFrame, col: str) -> int:
    """Sum a column as int, returning 0 if the column is absent or null."""
    return int(df[col].sum() or 0) if col in df.columns else 0


def _col_mean(df: pl.DataFrame, col: str) -> float:
    """Mean of a column, returning 0.0 if the column is absent."""
    return _safe_mean(df[col]) if col in df.columns else 0.0


def _compute_qb_advanced(athlete_id: str, name: str, season: int, gsis_id: str, pbp: pl.DataFrame) -> QBAdvancedStats:
    """Aggregate a quarterback's pass-play stats over a season."""
    if "passer_player_id" not in pbp.columns:
        return _empty_qb(athlete_id, name, season)
    pass_plays = pbp.filter((pl.col("passer_player_id") == gsis_id) & (pl.col("pass") == 1))
    attempts = pass_plays.height
    if attempts == 0:
        return _empty_qb(athlete_id, name, season)
    completions = _col_int_sum(pass_plays, "complete_pass")
    yards = _col_int_sum(pass_plays, "yards_gained")
    tds = _col_int_sum(pass_plays, "pass_touchdown")
    ints = _col_int_sum(pass_plays, "interception")
    completion_pct = completions / attempts
    ypa = yards / attempts
    return QBAdvancedStats(
        athlete_id=athlete_id,
        name=name,
        season=season,
        completion_percent=completion_pct,
        yards_per_attempt=ypa,
        touchdowns=tds,
        interceptions=ints,
        td_int_ratio=(tds / ints) if ints else float(tds),
        passer_rating=_passer_rating(completion_pct, ypa, tds, ints, attempts),
        cpoe=_col_mean(pass_plays, "cpoe"),
        epa_per_play=_col_mean(pass_plays, "epa"),
    )


def _empty_qb(athlete_id: str, name: str, season: int) -> QBAdvancedStats:
    """Build a zeroed QBAdvancedStats for a player with no pass attempts in the season."""
    return QBAdvancedStats(
        athlete_id=athlete_id,
        name=name,
        season=season,
        completion_percent=0.0,
        yards_per_attempt=0.0,
        touchdowns=0,
        interceptions=0,
        td_int_ratio=0.0,
        passer_rating=0.0,
        cpoe=0.0,
        epa_per_play=0.0,
    )


def _team_games(schedules: pl.DataFrame, team_abbr: str) -> pl.DataFrame:
    """Return only completed games involving the team (drops unplayed rows with null result)."""
    games = schedules.filter((pl.col("home_team") == team_abbr) | (pl.col("away_team") == team_abbr))
    if "result" in games.columns:
        games = games.filter(pl.col("result").is_not_null())
    return games


def _ats_outcome(team_abbr: str, home_team: str, spread_line: float, result: int) -> str:
    """Return 'win', 'loss', or 'push' for the team's ATS result on a single game.

    `spread_line` is the home team's spread (negative = home favored). `result`
    is `home_score - away_score`.
    """
    adjusted = result + spread_line if home_team == team_abbr else -(result + spread_line)
    if adjusted > 0:
        return "win"
    if adjusted < 0:
        return "loss"
    return "push"


def _ou_outcome(total_line: float, total: int) -> str:
    """Return 'over', 'under', or 'push' for an O/U bet on a single game."""
    if total > total_line:
        return "over"
    if total < total_line:
        return "under"
    return "push"


def _is_team_favorite(team_abbr: str, home_team: str, spread_line: float) -> bool:
    """True if the team was the favorite (laying points) in this game."""
    return spread_line < 0 if home_team == team_abbr else spread_line > 0


def _is_primetime(weekday: str | None, gametime: str | None) -> bool:
    """A game is primetime on Mon/Thu, or on Sun at or after 17:00 local."""
    if weekday in ("Mon", "Thu"):
        return True
    if weekday != "Sun":
        return False
    return _kickoff_hour(gametime) >= 17


def _kickoff_hour(gametime: str | None) -> int:
    """Parse the hour from an HH:MM gametime string. Returns 0 on bad/missing input."""
    if not gametime or ":" not in gametime:
        return 0
    try:
        return int(gametime.split(":", 1)[0])
    except ValueError:
        return 0


def _filter_situation(games: pl.DataFrame, team_abbr: str, situation: str) -> pl.DataFrame:
    """Apply a situational filter to the team's games."""
    if situation == "home":
        return games.filter(pl.col("home_team") == team_abbr)
    if situation == "away":
        return games.filter(pl.col("away_team") == team_abbr)
    rows = [g for g in games.iter_rows(named=True) if _row_matches_situation(g, team_abbr, situation)]
    return pl.from_dicts(rows, schema=games.schema) if rows else games.head(0)


def _row_matches_situation(row: dict, team_abbr: str, situation: str) -> bool:
    """Predicate for non-trivial situations (favorite/underdog/primetime)."""
    if situation == "favorite":
        return _is_team_favorite(team_abbr, row["home_team"], row["spread_line"])
    if situation == "underdog":
        return not _is_team_favorite(team_abbr, row["home_team"], row["spread_line"])
    if situation == "primetime":
        return _is_primetime(row.get("weekday"), row.get("gametime"))
    return False


def _compute_ats(team: Team, season: int, situation: str | None, schedules: pl.DataFrame) -> ATSRecord:
    """Tally the team's ATS record across the relevant games."""
    games = _team_games(schedules, team.abbreviation)
    if situation:
        games = _filter_situation(games, team.abbreviation, situation)
    wins = losses = pushes = 0
    for row in games.iter_rows(named=True):
        outcome = _ats_outcome(team.abbreviation, row["home_team"], row["spread_line"], row["result"])
        if outcome == "win":
            wins += 1
        elif outcome == "loss":
            losses += 1
        else:
            pushes += 1
    return ATSRecord(team=team, season=season, wins=wins, losses=losses, pushes=pushes, situation=situation)


def _compute_ou(team: Team, season: int, schedules: pl.DataFrame) -> OURecord:
    """Tally the team's over/under record across played games."""
    games = _team_games(schedules, team.abbreviation)
    overs = unders = pushes = 0
    for row in games.iter_rows(named=True):
        outcome = _ou_outcome(row["total_line"], row["total"])
        if outcome == "over":
            overs += 1
        elif outcome == "under":
            unders += 1
        else:
            pushes += 1
    return OURecord(team=team, season=season, overs=overs, unders=unders, pushes=pushes)


def _su_outcome(team_abbr: str, home_team: str, home_score: int, away_score: int) -> str:
    """Return the team's straight-up game outcome: 'win', 'loss', or 'tie'."""
    if home_team == team_abbr:
        team_score, opp_score = home_score, away_score
    else:
        team_score, opp_score = away_score, home_score
    if team_score > opp_score:
        return "win"
    if team_score < opp_score:
        return "loss"
    return "tie"


def _opponent_records(schedules: pl.DataFrame) -> dict[str, tuple[int, int, int]]:
    """Build a {team: (wins, losses, ties)} map from completed games."""
    records: dict[str, list[int]] = {}
    for row in schedules.iter_rows(named=True):
        if row.get("result") is None:
            continue
        result = row["result"]
        home, away = row["home_team"], row["away_team"]
        records.setdefault(home, [0, 0, 0])
        records.setdefault(away, [0, 0, 0])
        if result > 0:
            records[home][0] += 1
            records[away][1] += 1
        elif result < 0:
            records[away][0] += 1
            records[home][1] += 1
        else:
            records[home][2] += 1
            records[away][2] += 1
    return {k: (v[0], v[1], v[2]) for k, v in records.items()}


def _is_winning_record(record: tuple[int, int, int]) -> bool:
    """A team has a winning record if wins > losses."""
    return record[0] > record[1]


def _empty_like(games: pl.DataFrame) -> pl.DataFrame:
    """Return an empty DataFrame with the same schema as `games`."""
    return games.head(0)


def _filter_vs_winning(games: pl.DataFrame, all_schedules: pl.DataFrame, team_abbr: str) -> pl.DataFrame:
    """Keep games where the opponent finished the season with a winning record."""
    records = _opponent_records(all_schedules)
    keepers = []
    for row in games.iter_rows(named=True):
        opponent = row["away_team"] if row["home_team"] == team_abbr else row["home_team"]
        if _is_winning_record(records.get(opponent, (0, 0, 0))):
            keepers.append(row)
    return pl.from_dicts(keepers, schema=games.schema) if keepers else _empty_like(games)


def _filter_after_loss(games: pl.DataFrame, _all: pl.DataFrame, team_abbr: str) -> pl.DataFrame:
    """Keep games played immediately after a loss for the team."""
    sorted_games = games.sort("gameday") if "gameday" in games.columns else games
    keepers = []
    prev_outcome: str | None = None
    for row in sorted_games.iter_rows(named=True):
        if prev_outcome == "loss":
            keepers.append(row)
        if row.get("result") is not None:
            prev_outcome = _su_outcome(team_abbr, row["home_team"], row["home_score"], row["away_score"])
    return pl.from_dicts(keepers, schema=games.schema) if keepers else _empty_like(games)


def _filter_weekday(games: pl.DataFrame, _all: pl.DataFrame, _team: str, weekday: str) -> pl.DataFrame:
    return games.filter(pl.col("weekday") == weekday)


def _filter_snf(games: pl.DataFrame, _all: pl.DataFrame, _team: str) -> pl.DataFrame:
    return games.filter((pl.col("weekday") == "Sun") & (pl.col("gametime") >= "19:00"))


def _filter_roof(games: pl.DataFrame, _all: pl.DataFrame, _team: str, values: list[str]) -> pl.DataFrame:
    return games.filter(pl.col("roof").is_in(values))


_SITUATION_FILTERS = {
    "vs_winning": _filter_vs_winning,
    "after_loss": _filter_after_loss,
    "mnf": lambda g, a, t: _filter_weekday(g, a, t, "Mon"),
    "tnf": lambda g, a, t: _filter_weekday(g, a, t, "Thu"),
    "snf": _filter_snf,
    "dome": lambda g, a, t: _filter_roof(g, a, t, ["dome", "closed"]),
    "outdoor": lambda g, a, t: _filter_roof(g, a, t, ["outdoors", "open"]),
}


def _tally_situational(team_abbr: str, games: pl.DataFrame) -> tuple[int, int, int, int, int, int]:
    """Tally (su_w, su_l, su_t, ats_w, ats_l, ats_p) over a filtered set of games."""
    su_w = su_l = su_t = ats_w = ats_l = ats_p = 0
    for row in games.iter_rows(named=True):
        if row.get("result") is None:
            continue
        su = _su_outcome(team_abbr, row["home_team"], row["home_score"], row["away_score"])
        if su == "win":
            su_w += 1
        elif su == "loss":
            su_l += 1
        else:
            su_t += 1
        ats = _ats_outcome(team_abbr, row["home_team"], row["spread_line"], row["result"])
        if ats == "win":
            ats_w += 1
        elif ats == "loss":
            ats_l += 1
        else:
            ats_p += 1
    return su_w, su_l, su_t, ats_w, ats_l, ats_p


def _compute_situational(team: Team, season: int, situation: str, all_schedules: pl.DataFrame) -> SituationalRecord:
    """Build a SituationalRecord by filtering then tallying."""
    games = _team_games(all_schedules, team.abbreviation)
    filtered = _SITUATION_FILTERS[situation](games, all_schedules, team.abbreviation)
    su_w, su_l, su_t, ats_w, ats_l, ats_p = _tally_situational(team.abbreviation, filtered)
    return SituationalRecord(
        team=team,
        season=season,
        situation=situation,
        su_wins=su_w,
        su_losses=su_l,
        su_ties=su_t,
        ats_wins=ats_w,
        ats_losses=ats_l,
        ats_pushes=ats_p,
    )


def _passer_rating(completion_pct: float, ypa: float, tds: int, ints: int, attempts: int) -> float:
    """Compute the NFL passer rating (0–158.3) from per-attempt rates.

    See https://en.wikipedia.org/wiki/Passer_rating#NFL_and_CFL_formula. Each
    component is clamped to [0, 2.375] before averaging.
    """
    if attempts == 0:
        return 0.0
    a = max(0.0, min(2.375, (completion_pct - 0.3) * 5))
    b = max(0.0, min(2.375, (ypa - 3.0) * 0.25))
    c = max(0.0, min(2.375, (tds / attempts) * 20))
    d = max(0.0, min(2.375, 2.375 - (ints / attempts) * 25))
    return ((a + b + c + d) / 6.0) * 100.0
