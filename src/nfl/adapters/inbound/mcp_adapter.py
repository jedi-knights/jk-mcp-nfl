"""Inbound adapter — exposes the application service as MCP tools.

FastMCP generates tool schemas from Python type hints and docstrings, so the
docstrings on each registered tool are the LLM's primary guide.

Logging note (STDIO transport): NEVER use print() here. It writes to stdout
and corrupts the JSON-RPC stream.
"""

import logging
from collections.abc import Awaitable, Callable

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from starlette.requests import Request
from starlette.responses import JSONResponse

from ...application.service import NFLService
from ...domain.exceptions import NFLNotFoundError, UpstreamAPIError
from .formatters import (
    _fmt_athlete,
    _fmt_ats_record,
    _fmt_def_points_per_100,
    _fmt_head_to_head,
    _fmt_injuries,
    _fmt_news,
    _fmt_odds,
    _fmt_ou_record,
    _fmt_qb_advanced,
    _fmt_red_zone,
    _fmt_roster,
    _fmt_schedule,
    _fmt_scoreboard,
    _fmt_situational_record,
    _fmt_standings,
    _fmt_success_rate,
    _fmt_team,
    _fmt_team_epa,
    _fmt_team_stats,
    _fmt_teams,
    _fmt_third_down,
    _fmt_weather,
)

logger = logging.getLogger(__name__)

_READ_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=True,
)


async def _safe_call[T](coro: Awaitable[T], fmt: Callable[[T], str]) -> str:
    """Await coro, apply fmt to the result, and convert domain exceptions to error strings."""
    try:
        return fmt(await coro)
    except NFLNotFoundError as exc:
        logger.warning("Not found: %s", exc)
        return f"Not found: {exc}"
    except UpstreamAPIError as exc:
        logger.error("Upstream API error: %s", exc)
        return f"Upstream error: {exc}"
    except ValueError as exc:
        logger.warning("Invalid request: %s", exc)
        return f"Invalid request: {exc}"
    except RuntimeError as exc:
        logger.error("Service misconfiguration: %s", exc)
        return f"Unavailable: {exc}"


async def _handle_livez(request: Request) -> JSONResponse:
    """Liveness probe — returns 200 OK if the HTTP server is up."""
    return JSONResponse({"status": "ok"})


async def _handle_readyz(request: Request) -> JSONResponse:
    """Readiness probe — returns 200 when the server is ready to serve traffic."""
    return JSONResponse({"status": "ok"})


async def _handle_health(request: Request) -> JSONResponse:
    """Aggregate health endpoint for monitoring systems."""
    return JSONResponse({"status": "ok", "checks": {"liveness": "ok", "readiness": "ok"}})


def create_mcp_server(service: NFLService, host: str = "0.0.0.0", port: int = 8000) -> FastMCP:
    """Wire the application service into a FastMCP instance and register tools."""
    mcp = FastMCP("nfl", host=host, port=port, stateless_http=True)

    mcp.custom_route("/livez", methods=["GET"])(_handle_livez)
    mcp.custom_route("/readyz", methods=["GET"])(_handle_readyz)
    mcp.custom_route("/health", methods=["GET"])(_handle_health)

    @mcp.tool(annotations=_READ_ANNOTATIONS)
    async def get_teams() -> str:
        """Get all active NFL teams.

        Returns a numbered list of teams with their ID, full name, and
        abbreviation. Use the ID with get_team for detailed information.
        """
        logger.info("tool=get_teams")
        return await _safe_call(service.get_teams(), _fmt_teams)

    @mcp.tool(annotations=_READ_ANNOTATIONS)
    async def get_team(team_id: str) -> str:
        """Get details for a specific NFL team.

        Args:
            team_id: ESPN numeric team ID (e.g. "12" for the Kansas City Chiefs).
        """
        logger.info("tool=get_team team_id=%r", team_id)
        return await _safe_call(service.get_team(team_id), _fmt_team)

    @mcp.tool(annotations=_READ_ANNOTATIONS)
    async def get_scoreboard(date: str | None = None) -> str:
        """Get NFL game scores and status for a date.

        With no argument, returns games for the current NFL week. With a date,
        returns games on that day (and the week containing it).

        Args:
            date: Optional date string in YYYYMMDD format (e.g. "20260105").
        """
        logger.info("tool=get_scoreboard date=%r", date)
        return await _safe_call(service.get_scoreboard(date), _fmt_scoreboard)

    @mcp.tool(annotations=_READ_ANNOTATIONS)
    async def get_standings() -> str:
        """Get the current NFL standings.

        Returns teams ordered by win percentage (descending), with W-L-T,
        points for, points against, and point differential.
        """
        logger.info("tool=get_standings")
        return await _safe_call(service.get_standings(), _fmt_standings)

    @mcp.tool(annotations=_READ_ANNOTATIONS)
    async def get_team_stats(team_id: str, season: int | None = None) -> str:
        """Get season-level efficiency stats for an NFL team.

        Returns games played, points per game, point differential, and (when
        available) yards-per-game allowed, yards-per-play, and turnover
        differential. Yardage and turnover figures are not always available
        from the upstream feed and may show as "n/a".

        Args:
            team_id: ESPN numeric team ID (e.g. "12" for the Kansas City Chiefs).
            season: Optional season year (e.g. 2025). Defaults to current season.
        """
        logger.info("tool=get_team_stats team_id=%r season=%r", team_id, season)
        return await _safe_call(service.get_team_stats(team_id, season), _fmt_team_stats)

    @mcp.tool(annotations=_READ_ANNOTATIONS)
    async def get_team_schedule(team_id: str, season: int | None = None) -> str:
        """Get a team's full schedule for a season.

        Args:
            team_id: ESPN numeric team ID.
            season: Optional season year. Defaults to the current season.
        """
        logger.info("tool=get_team_schedule team_id=%r season=%r", team_id, season)
        return await _safe_call(service.get_team_schedule(team_id, season), _fmt_schedule)

    @mcp.tool(annotations=_READ_ANNOTATIONS)
    async def get_head_to_head(team_a: str, team_b: str, last_n: int = 5) -> str:
        """Get the head-to-head record between two NFL teams across recent seasons.

        Returns a W-L-T summary from team_a's perspective plus the most recent
        matchups (up to last_n).

        Args:
            team_a: ESPN numeric team ID for the first team.
            team_b: ESPN numeric team ID for the second team.
            last_n: Maximum number of recent matchups to include (default 5).
        """
        logger.info("tool=get_head_to_head team_a=%r team_b=%r last_n=%r", team_a, team_b, last_n)
        return await _safe_call(service.get_head_to_head(team_a, team_b, last_n), _fmt_head_to_head)

    @mcp.tool(annotations=_READ_ANNOTATIONS)
    async def get_roster(team_id: str) -> str:
        """Get the active roster for an NFL team.

        Args:
            team_id: ESPN numeric team ID.
        """
        logger.info("tool=get_roster team_id=%r", team_id)
        return await _safe_call(service.get_roster(team_id), _fmt_roster)

    @mcp.tool(annotations=_READ_ANNOTATIONS)
    async def get_injuries(team_id: str | None = None) -> str:
        """Get the current NFL injury report.

        Args:
            team_id: Optional ESPN numeric team ID to scope the report to a
                single team. Omit for the league-wide report.
        """
        logger.info("tool=get_injuries team_id=%r", team_id)
        return await _safe_call(service.get_injuries(team_id), _fmt_injuries)

    @mcp.tool(annotations=_READ_ANNOTATIONS)
    async def get_athlete(athlete_id: str) -> str:
        """Get profile information for a single NFL athlete.

        Args:
            athlete_id: ESPN numeric athlete ID.
        """
        logger.info("tool=get_athlete athlete_id=%r", athlete_id)
        return await _safe_call(service.get_athlete(athlete_id), _fmt_athlete)

    @mcp.tool(annotations=_READ_ANNOTATIONS)
    async def get_news(team_id: str | None = None, limit: int = 10) -> str:
        """Get recent NFL news headlines.

        Args:
            team_id: Optional ESPN numeric team ID to scope news to one team.
            limit: Maximum number of articles (default 10, capped at 50).
        """
        logger.info("tool=get_news team_id=%r limit=%r", team_id, limit)
        return await _safe_call(service.get_news(team_id, limit), _fmt_news)

    @mcp.tool(annotations=_READ_ANNOTATIONS)
    async def get_team_epa(team_id: str, season: int | None = None, side: str = "offense") -> str:
        """Get Expected Points Added per play for one side of an NFL team.

        Args:
            team_id: ESPN numeric team ID.
            season: Optional season year. Defaults to the current season.
            side: "offense" or "defense" (default "offense"). Defense EPA is
                the EPA the team allowed; lower (more negative) is better.
        """
        logger.info("tool=get_team_epa team_id=%r season=%r side=%r", team_id, season, side)
        return await _safe_call(service.get_team_epa(team_id, season, side), _fmt_team_epa)

    @mcp.tool(annotations=_READ_ANNOTATIONS)
    async def get_success_rate(team_id: str, season: int | None = None) -> str:
        """Get a team's offensive and defensive success rates for a season.

        Success rate is the share of plays that meet a down-and-distance
        success threshold (typically EPA-positive).

        Args:
            team_id: ESPN numeric team ID.
            season: Optional season year.
        """
        logger.info("tool=get_success_rate team_id=%r season=%r", team_id, season)
        return await _safe_call(service.get_success_rate(team_id, season), _fmt_success_rate)

    @mcp.tool(annotations=_READ_ANNOTATIONS)
    async def get_third_down_rate(team_id: str, season: int | None = None) -> str:
        """Get a team's third-down conversion rates as offense and defense.

        Args:
            team_id: ESPN numeric team ID.
            season: Optional season year.
        """
        logger.info("tool=get_third_down_rate team_id=%r season=%r", team_id, season)
        return await _safe_call(service.get_third_down_rate(team_id, season), _fmt_third_down)

    @mcp.tool(annotations=_READ_ANNOTATIONS)
    async def get_red_zone_efficiency(team_id: str, season: int | None = None) -> str:
        """Get a team's red zone touchdown rates as offense and defense.

        Bettors commonly flag red zone TD rate >= 60% as a strong offense.

        Args:
            team_id: ESPN numeric team ID.
            season: Optional season year.
        """
        logger.info("tool=get_red_zone_efficiency team_id=%r season=%r", team_id, season)
        return await _safe_call(service.get_red_zone_efficiency(team_id, season), _fmt_red_zone)

    @mcp.tool(annotations=_READ_ANNOTATIONS)
    async def get_def_points_per_100_yards(team_id: str, season: int | None = None) -> str:
        """Get the "Defensive Points per 100 Yards" power stat for a team.

        Formula: (yards_allowed / 100) / points_allowed. Bands: <6.0 good,
        6.0-7.0 average, >7.0 poor (per sportsbettingstats handicapping).

        Args:
            team_id: ESPN numeric team ID.
            season: Optional season year.
        """
        logger.info("tool=get_def_points_per_100_yards team_id=%r season=%r", team_id, season)
        return await _safe_call(
            service.get_def_points_per_100_yards(team_id, season),
            _fmt_def_points_per_100,
        )

    @mcp.tool(annotations=_READ_ANNOTATIONS)
    async def get_ats_record(team_id: str, season: int | None = None, situation: str | None = None) -> str:
        """Get a team's against-the-spread record for a season.

        Args:
            team_id: ESPN numeric team ID.
            season: Optional season year. Defaults to the current season.
            situation: Optional scope — one of "home", "away", "favorite",
                "underdog", "primetime". Omit for the overall record.
        """
        logger.info("tool=get_ats_record team_id=%r season=%r situation=%r", team_id, season, situation)
        return await _safe_call(service.get_ats_record(team_id, season, situation), _fmt_ats_record)

    @mcp.tool(annotations=_READ_ANNOTATIONS)
    async def get_ou_record(team_id: str, season: int | None = None) -> str:
        """Get a team's Over/Under record for a season.

        Args:
            team_id: ESPN numeric team ID.
            season: Optional season year. Defaults to the current season.
        """
        logger.info("tool=get_ou_record team_id=%r season=%r", team_id, season)
        return await _safe_call(service.get_ou_record(team_id, season), _fmt_ou_record)

    @mcp.tool(annotations=_READ_ANNOTATIONS)
    async def get_current_odds(bookmaker: str = "draftkings") -> str:
        """Get current sportsbook lines (spread, total, ML) for upcoming NFL games.

        Returns one row per game from the requested bookmaker. Spread is from
        the home team's perspective (negative = home favored). Requires the
        ODDS_API_KEY env var to be set on the server; otherwise returns an
        "Unavailable" message.

        Args:
            bookmaker: The Odds API bookmaker key (default "draftkings").
                Other examples: "fanduel", "betmgm", "caesars".
        """
        logger.info("tool=get_current_odds bookmaker=%r", bookmaker)
        return await _safe_call(service.get_current_odds(bookmaker), _fmt_odds)

    @mcp.tool(annotations=_READ_ANNOTATIONS)
    async def get_game_weather(home_team_id: str, date: str) -> str:
        """Get kickoff-hour weather at the home team's stadium for a given date.

        Domes return "indoor" without an HTTP call. Outdoor stadiums return
        temperature, wind, precipitation, and condition for ~4pm local.

        Args:
            home_team_id: ESPN numeric team ID for the home team.
            date: Game date in YYYYMMDD format (e.g. "20260105").
        """
        logger.info("tool=get_game_weather home_team_id=%r date=%r", home_team_id, date)
        return await _safe_call(service.get_game_weather(home_team_id, date), _fmt_weather)

    @mcp.tool(annotations=_READ_ANNOTATIONS)
    async def get_situational_record(team_id: str, situation: str, season: int | None = None) -> str:
        """Get a team's straight-up + ATS records in a broader situational scope.

        Supports situations beyond `get_ats_record`: vs winning teams, after a
        loss, primetime time slots (MNF/TNF/SNF), and venue type (dome/outdoor).

        Args:
            team_id: ESPN numeric team ID.
            situation: One of "vs_winning", "after_loss", "mnf", "tnf",
                "snf", "dome", "outdoor".
            season: Optional season year. Defaults to the current season.
        """
        logger.info("tool=get_situational_record team_id=%r situation=%r season=%r", team_id, situation, season)
        return await _safe_call(
            service.get_situational_record(team_id, situation, season),
            _fmt_situational_record,
        )

    @mcp.tool(annotations=_READ_ANNOTATIONS)
    async def get_qb_advanced(athlete_id: str, season: int | None = None) -> str:
        """Get advanced quarterback efficiency stats for a season.

        Returns completion %, yards per attempt, TDs, INTs, TD:INT ratio,
        passer rating, CPOE (Completion % Over Expected), and EPA/play.

        Args:
            athlete_id: ESPN numeric athlete ID for the QB.
            season: Optional season year. Defaults to the current season.
        """
        logger.info("tool=get_qb_advanced athlete_id=%r season=%r", athlete_id, season)
        return await _safe_call(service.get_qb_advanced(athlete_id, season), _fmt_qb_advanced)

    return mcp
