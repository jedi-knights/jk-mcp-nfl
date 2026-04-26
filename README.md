# jk-mcp-nfl

[![Python](https://img.shields.io/badge/python-3.13-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

An **MCP server** that gives Claude direct access to live NFL data — teams,
scores, standings — via the ESPN public API. No API key required.

> **Status:** early scaffold. Four read-only tools wired end-to-end. Designed
> to grow into roster/schedule/match-detail/news/stats/analytics tools as the
> domain stabilizes.

---

## Tools

| Tool | Description |
|---|---|
| `get_teams` | List all 32 active NFL teams with IDs and abbreviations |
| `get_team` | Get details for a specific team by ESPN team ID |
| `get_scoreboard` | Get game scores for a date (or current week if no date given) |
| `get_standings` | Get current NFL standings ordered by win % then point differential |

All tools are read-only and idempotent. Backed by the **ESPN public API**
(`site.api.espn.com`). Endpoints were derived from the public website's
backing JSON; if a tool stops working the upstream format likely changed.

---

## Requirements

- [Python 3.13+](https://www.python.org/downloads/)
- [uv](https://docs.astral.sh/uv/getting-started/installation/)

---

## Quickstart

```sh
git clone https://github.com/jedi-knights/jk-mcp-nfl.git
cd jk-mcp-nfl
uv sync
```

Run the server in stdio mode (the default — used by Claude Code and Claude Desktop):

```sh
uv run python -m nfl.server
```

Run in HTTP mode (for networked or deployed access):

```sh
MCP_TRANSPORT=streamable-http uv run python -m nfl.server
```

---

## Configuration

All configuration is via environment variables. None are required for local use.

| Variable | Default | Description |
|---|---|---|
| `MCP_TRANSPORT` | `stdio` | Transport mode: `stdio` or `streamable-http` |
| `HOST` | `0.0.0.0` | Bind address (HTTP transport only) |
| `PORT` | `8000` | TCP port (HTTP transport only) |
| `API_HOST` | `https://site.api.espn.com` | ESPN API base URL |
| `LOG_LEVEL` | `INFO` | Log level: `DEBUG`, `INFO`, `WARNING`, `ERROR` |

---

## Claude Code

Register the local clone globally:

```sh
claude mcp add --scope user nfl -- uv run --directory /path/to/jk-mcp-nfl python -m nfl.server
```

Verify with `claude mcp list`. Restart Claude Code if it was running.

---

## Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS):

```json
{
  "mcpServers": {
    "nfl": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/jk-mcp-nfl", "python", "-m", "nfl.server"]
    }
  }
}
```

Restart Claude Desktop after saving.

---

## Development

### Install dependencies

```sh
uv sync
```

### Common tasks

| Task | Description |
|---|---|
| `uv run inv test` | Run the full test suite |
| `uv run inv coverage` | Run tests with coverage report (threshold: 90%) |
| `uv run inv lint` | Run ruff linter and format check |
| `uv run inv lint --fix` | Auto-fix lint violations and reformat |
| `uv run inv check-complexity` | Check cyclomatic complexity (max 7) |

### Project structure

```
src/nfl/
├── server.py                  # entry point, transport selection, logging setup
├── adapters/
│   ├── inbound/
│   │   ├── mcp_adapter.py     # FastMCP tools, request formatting
│   │   └── formatters.py      # domain → text helpers
│   └── outbound/
│       ├── espn_adapter.py    # ESPN HTTP client
│       ├── parsers.py         # ESPN JSON → domain
│       ├── retry_adapter.py   # retry decorator for transient failures
│       └── caching_adapter.py # in-process response cache
├── application/
│   └── service.py             # use cases, orchestration
├── domain/
│   ├── models.py              # Team, Match, Standing
│   └── exceptions.py          # NFLNotFoundError, UpstreamAPIError
└── ports/
    └── outbound.py            # Protocol interface for driven adapters
```

The dependency direction flows inward: adapters → ports → domain. Nothing in
`domain/` imports from adapters or the framework.

---

## License

MIT — see [LICENSE](LICENSE).
