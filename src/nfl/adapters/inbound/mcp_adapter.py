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
from .formatters import _fmt_scoreboard, _fmt_standings, _fmt_team, _fmt_teams

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

    return mcp
