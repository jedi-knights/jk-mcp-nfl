# jk-mcp-nfl

[![Python](https://img.shields.io/badge/python-3.13-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

An **MCP server** that gives Claude direct access to live NFL data — teams,
scores, standings, advanced analytics, betting splits, and weather — via free
public data sources. The 21 core tools require no API key; one optional tool
adds live sportsbook lines if you provide a (free-tier) Odds API key.

> **Status:** 22 read-only tools wired across four data sources (ESPN, nflverse,
> Open-Meteo, The Odds API). See [docs/RESEARCH.md](docs/RESEARCH.md) for the
> betting-stats research that drove the tool design.

---

## Tools

### League data (ESPN)

| Tool | Description |
|---|---|
| `get_teams` | List all 32 active NFL teams with IDs and abbreviations |
| `get_team` | Details for a specific team by ESPN team ID |
| `get_scoreboard` | Game scores for a date (or current week if no date given) |
| `get_standings` | Current NFL standings ordered by win % then point differential |
| `get_team_stats` | Season-level efficiency totals for a team (PPG, point diff) |
| `get_team_schedule` | Full season schedule for a team |
| `get_head_to_head` | Recent matchups between two teams across the last 5 seasons |
| `get_roster` | Active roster for a team |
| `get_injuries` | Current injury report (team-scoped or league-wide) |
| `get_athlete` | Profile for a single athlete by ESPN athlete ID |
| `get_news` | Recent NFL headlines (team-scoped or league-wide) |

### Advanced stats (nflverse)

| Tool | Description |
|---|---|
| `get_team_epa` | EPA/play, pass EPA, rush EPA, success rate for one side of the ball |
| `get_success_rate` | Offensive + defensive success rate with play counts |
| `get_third_down_rate` | Third-down conversion rates as offense and defense |
| `get_red_zone_efficiency` | Red zone TD rates (offense + defense). Bettors flag offense ≥ 60% as strong |
| `get_def_points_per_100_yards` | The "DEF pts/100 yds" power stat with good/average/poor rating |
| `get_qb_advanced` | QB CPOE, EPA/play, passer rating, TDs, INTs, completion %, YPA |
| `get_ats_record` | Against-the-spread record, optionally scoped to home/away/favorite/underdog/primetime |
| `get_ou_record` | Over/Under record for the season |
| `get_situational_record` | SU+ATS records for vs winning teams, after a loss, MNF/TNF/SNF, dome/outdoor |

### Weather (Open-Meteo)

| Tool | Description |
|---|---|
| `get_game_weather` | Kickoff-hour weather at the home team's stadium. Domes return "indoor" |

### Live odds (The Odds API — optional, requires API key)

| Tool | Description |
|---|---|
| `get_current_odds` | Current spread, total, and moneylines per upcoming game from one bookmaker |

`get_current_odds` only registers if `ODDS_API_KEY` is set; otherwise it
returns "Unavailable" so the rest of the server keeps working.

All tools are read-only and idempotent.

### Data sources

| Source | Access | What it provides |
|---|---|---|
| [ESPN public API](https://site.api.espn.com) | free, no key | teams, scoreboard, standings, schedules, rosters, injuries, news |
| [nflverse-data](https://github.com/nflverse/nflverse-data) | free, no key | per-season parquet artifacts: play-by-play (EPA/CPOE/success), schedules with lines/totals/results, rosters |
| [Open-Meteo](https://open-meteo.com) | free, no key | forecast + archive weather at stadium lat/lon |
| [The Odds API](https://the-odds-api.com) | free tier (500 req/mo), key required | live sportsbook lines (spreads, totals, moneylines) per upcoming game |

nflverse parquets are downloaded once per season and cached on disk. Past
seasons never re-download; the current season refreshes every 24 hours.

---

## Example prompts

Natural-language prompts a user can ask Claude (or any MCP client) and the
tool each one fires. ESPN team IDs and athlete IDs are stable — Claude will
typically resolve them by name first via `get_teams` / `get_athlete`.

### League data

| Prompt | Tool |
|---|---|
| "List all NFL teams" | `get_teams` |
| "Show me details for the Kansas City Chiefs" | `get_team` |
| "What were the NFL scores last Sunday?" | `get_scoreboard` |
| "How are the current NFL standings looking?" | `get_standings` |
| "How are the Bills doing this season — record, points, differential?" | `get_team_stats` |
| "Show me the Chiefs' full schedule for 2025" | `get_team_schedule` |
| "What's the recent head-to-head between the Chiefs and Bills?" | `get_head_to_head` |
| "Who's on the Chiefs' active roster?" | `get_roster` |
| "Who's on the injury report this week?" | `get_injuries` (no team) |
| "Any Bills players hurt right now?" | `get_injuries` (team-scoped) |
| "Tell me about Patrick Mahomes" | `get_athlete` |
| "What's the latest NFL news?" | `get_news` |
| "Any recent Chiefs news?" | `get_news` (team-scoped) |

### Advanced stats and betting splits

| Prompt | Tool |
|---|---|
| "How efficient is the Chiefs offense this year by EPA?" | `get_team_epa` (side=offense) |
| "Is the Chiefs defense any good in EPA terms?" | `get_team_epa` (side=defense) |
| "Compare the Chiefs' offensive and defensive success rates" | `get_success_rate` |
| "How are the Chiefs converting on third down?" | `get_third_down_rate` |
| "Are the Chiefs scoring TDs in the red zone, and how often?" | `get_red_zone_efficiency` |
| "Is the Chiefs defense good or poor by points-per-100-yards?" | `get_def_points_per_100_yards` |
| "What are Mahomes' advanced QB stats this season — CPOE, EPA, passer rating?" | `get_qb_advanced` |
| "How are the Chiefs against the spread overall?" | `get_ats_record` (no situation) |
| "How do the Chiefs do ATS as a home favorite?" | `get_ats_record` (situation=favorite) |
| "Are Chiefs games typically over or under?" | `get_ou_record` |
| "How do the Chiefs perform on Monday Night Football?" | `get_situational_record` (mnf) |
| "How do the Bills do after a loss?" | `get_situational_record` (after_loss) |
| "How do the Bears do in domes?" | `get_situational_record` (dome) |

### Weather

| Prompt | Tool |
|---|---|
| "What's the weather forecast for Sunday's Bills home game?" | `get_game_weather` |
| "What were the conditions when the Chiefs played at Buffalo on 2025-09-15?" | `get_game_weather` (past date → archive) |

### Live odds *(requires `ODDS_API_KEY`)*

| Prompt | Tool |
|---|---|
| "What are the current spreads on this week's NFL games?" | `get_current_odds` |
| "Show me the FanDuel lines for upcoming games" | `get_current_odds` (bookmaker=fanduel) |

### Cross-tool prompts

The real value comes from chaining tools. A handicapping question like
"Should I bet the Chiefs at home this Sunday?" will typically fire a
sequence of calls — `get_team` to resolve the ID, then several of:
`get_team_stats`, `get_team_epa`, `get_red_zone_efficiency`,
`get_def_points_per_100_yards`, `get_ats_record` (situation=home),
`get_injuries`, `get_game_weather`, and (if configured) `get_current_odds`.

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
| `NFLVERSE_CACHE_DIR` | `~/.cache/jk-mcp-nfl/nflverse` | On-disk cache directory for nflverse parquet files |
| `ODDS_API_KEY` | _(unset)_ | API key for The Odds API. Without it, `get_current_odds` returns "Unavailable" but every other tool still works |
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
├── server.py                     # entry point, transport selection, logging setup
├── adapters/
│   ├── inbound/
│   │   ├── mcp_adapter.py        # FastMCP tools, request formatting
│   │   └── formatters.py         # domain → text helpers
│   └── outbound/
│       ├── espn_adapter.py       # ESPN HTTP client
│       ├── parsers.py            # ESPN JSON → domain
│       ├── nflverse_adapter.py   # nflverse parquet download/cache + analytics
│       ├── openmeteo_adapter.py  # Open-Meteo weather + stadium map
│       ├── odds_adapter.py       # The Odds API live lines (optional)
│       ├── retry_proxy.py        # generic retry decorator (any async port)
│       └── caching_proxy.py      # generic TTL-cache decorator (any async port)
├── application/
│   └── service.py                # use cases, orchestration across all ports
├── domain/
│   ├── models.py                 # Team, Match, Standing, EPAStats, ATSRecord, etc.
│   └── exceptions.py             # NFLNotFoundError, UpstreamAPIError, SeasonNotAvailableError
└── ports/
    └── outbound.py               # NFLAPIPort, NFLDataPort, WeatherPort, OddsPort
```

The dependency direction flows inward: adapters → ports → domain. Nothing in
`domain/` imports from adapters or the framework.

---

## License

MIT — see [LICENSE](LICENSE).
