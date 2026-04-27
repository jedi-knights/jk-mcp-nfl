"""Entry point for the NFL MCP server.

Wires together the outbound adapter (ESPN HTTP), the application service, and
the inbound MCP adapter. The dependency graph flows inward — adapters depend
on ports, ports depend on domain models. Nothing here is circular.

Transport: controlled by the MCP_TRANSPORT environment variable.
- "stdio" (default): JSON-RPC over stdin/stdout — client spawns the server as
  a subprocess. Never write to stdout in this mode; it corrupts the message stream.
- "streamable-http": HTTP server on HOST:PORT. Use this for deployed access.

ESPN API host: controlled by the API_HOST environment variable.
- Default: https://site.api.espn.com

Structured logging: all log records are emitted as JSON objects to stderr.
"""

import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from .adapters.inbound.mcp_adapter import create_mcp_server
from .adapters.outbound.caching_proxy import CachingProxy
from .adapters.outbound.espn_adapter import ESPNAdapter
from .adapters.outbound.nflverse_adapter import NFLVerseAdapter
from .adapters.outbound.odds_adapter import OddsAPIAdapter
from .adapters.outbound.openmeteo_adapter import OpenMeteoAdapter
from .adapters.outbound.retry_proxy import RetryingProxy
from .application.service import NFLService


class _JsonFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry)


def _configure_logging() -> None:
    """Configure the root logger to emit JSON records to stderr."""
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_JsonFormatter())
    logging.root.setLevel(level)
    logging.root.addHandler(handler)


load_dotenv()
_configure_logging()

logger = logging.getLogger(__name__)

_VALID_TRANSPORTS = ("stdio", "streamable-http")


def build_server(
    host: str = "0.0.0.0",
    port: int = 8000,
    api_host: str = "https://site.api.espn.com",
    nflverse_cache_dir: str | None = None,
    odds_api_key: str | None = None,
) -> FastMCP:
    """Wire all outbound adapters → NFLService → FastMCP and return the server.

    Every outbound adapter is wrapped in the generic retry + caching proxies.
    TTLs reflect each source's update cadence:
      - ESPN league feed: 5 min default; scoreboard 60s (live game updates).
      - nflverse parquet analytics: 10 min (files update infrequently).
      - Open-Meteo weather: 5 min (forecasts evolve slowly).
      - Odds API: 1 min (live lines change quickly; conserve free-tier quota).
    """
    cache_dir = Path(nflverse_cache_dir or Path.home() / ".cache" / "jk-mcp-nfl" / "nflverse")
    espn = CachingProxy(
        RetryingProxy(ESPNAdapter(base_url=api_host)),
        ttl_seconds=300,
        ttl_overrides={"get_scoreboard": 60.0},
    )
    nflverse = CachingProxy(RetryingProxy(NFLVerseAdapter(cache_dir=cache_dir)), ttl_seconds=600)
    weather = CachingProxy(RetryingProxy(OpenMeteoAdapter()), ttl_seconds=300)
    # Live odds are optional — only wired if an API key was provided.
    odds = CachingProxy(RetryingProxy(OddsAPIAdapter(api_key=odds_api_key)), ttl_seconds=60) if odds_api_key else None
    service = NFLService(repo=espn, data_repo=nflverse, weather_repo=weather, odds_repo=odds)
    return create_mcp_server(service, host=host, port=port)


def main() -> None:
    """Start the NFL MCP server.

    Reads configuration from the environment:
      API_HOST       — base URL of the upstream ESPN API (default: https://site.api.espn.com)
      MCP_TRANSPORT  — "stdio" (default) or "streamable-http"
      HOST           — bind address for HTTP transport (default: 0.0.0.0)
      PORT           — TCP port for HTTP transport (default: 8000)
    """
    api_host = os.environ.get("API_HOST", "https://site.api.espn.com")
    transport = os.environ.get("MCP_TRANSPORT", "stdio").lower()
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    nflverse_cache_dir = os.environ.get("NFLVERSE_CACHE_DIR")
    odds_api_key = os.environ.get("ODDS_API_KEY")

    if transport not in _VALID_TRANSPORTS:
        raise ValueError(f"Invalid MCP_TRANSPORT={transport!r}. Must be one of: {', '.join(_VALID_TRANSPORTS)}")

    if transport == "streamable-http":
        logger.info("Starting NFL MCP server (streamable-http transport, %s:%s)", host, port)
        build_server(
            host=host,
            port=port,
            api_host=api_host,
            nflverse_cache_dir=nflverse_cache_dir,
            odds_api_key=odds_api_key,
        ).run(transport="streamable-http")
    else:
        logger.info("Starting NFL MCP server (stdio transport)")
        build_server(
            api_host=api_host,
            nflverse_cache_dir=nflverse_cache_dir,
            odds_api_key=odds_api_key,
        ).run(transport="stdio")


if __name__ == "__main__":
    main()
