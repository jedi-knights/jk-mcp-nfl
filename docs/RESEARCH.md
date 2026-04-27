# Research: NFL Betting Stats → MCP Tool Proposals

This document captures research into the statistics that NFL bettors and
handicappers actually use, and translates those findings into a concrete
roadmap of tools to add to the `jk-mcp-nfl` MCP server.

## Sources reviewed

| URL | Status |
|---|---|
| https://www.frontproofmedia.com/football/key-stats-to-focus-on-when-betting-on-nfl-games | fetched |
| https://windailysports.com/key-statistics-for-successful-nfl-betting/ | fetched |
| https://sportsbettingstats.com/nfl/picks/nfl-handicapping-power-stats/ | fetched |
| https://1010xl.com/post/master-the-metrics-nfl-betting-stats-that-actually-move-the-needle/ | 403 — content inferred from genre |
| https://rg.org/guides/understanding-trends-and-statistics/nfl-betting-trends-and-statistics | 403 — content inferred from genre |

The two blocked URLs cover well-trodden ground (situational ATS trends,
public-betting %, divisional matchups, primetime/short-week records). Their
absence does not change the proposal materially.

## Recurring themes

| Theme | Stats called out by the articles |
|---|---|
| Team efficiency | PPG, YAPG, yards per play, point differential |
| QB play | passer rating, completion %, YPA, TD:INT |
| Turnovers | turnover differential, ball security |
| Red zone | TD conversion rate (60%+ threshold cited) |
| Defense (power stat) | "Defensive Points per 100 Yards" — sportsbettingstats' featured metric, range ~6.0–7.0 |
| Situational splits | home/away win %, divisional, primetime, after bye, short week, time zones |
| ATS / O-U trends | ATS record, O/U record, line movement, public betting % |
| Advanced | DVOA, EPA / Expected Points Contributed |
| Context | weather (wind/rain/snow/temp extremes), injuries, head-to-head history |

Notable quotes:

- Home field advantage cited at ~57% historical win rate (windailysports).
- Extreme cold cited as 15–20% scoring decrease (windailysports).
- "Defensive Points per 100 Yards" formula: `points_allowed / (yards_allowed / 100)`; <6.0 good, >7.0 poor (sportsbettingstats). Lower is better — fewer points conceded per 100 yards of defense.
- Red zone TD conversion ≥60% is the "good offense" threshold (frontproof).

## Proposed tools

Organized in tiers by data-source dependency. Each tool is read-only,
idempotent, and follows the existing inbound `mcp_adapter.py` pattern.

### Tier 1 — Extend ESPN (no new outbound dependency)

The existing `espn_adapter` already speaks `site.api.espn.com`. These tools
just hit additional endpoints on the same host.

| Tool | Args | Returns |
|---|---|---|
| `get_team_stats` | `team_id, season?` | PPG, YAPG, YPP, point differential, turnover differential |
| `get_team_schedule` | `team_id, season?` | Full schedule with results |
| `get_roster` | `team_id` | Active roster with positions |
| `get_injuries` | `team_id?` | Current injury report |
| `get_athlete` | `athlete_id` | Player bio + season stats |
| `get_news` | `team_id?, limit?` | Recent headlines (ESPN news endpoint) |
| `get_head_to_head` | `team_a, team_b, last_n?` | Historical matchups |

### Tier 2 — Add nflverse-data adapter (free, no API key)

The biggest leverage point. nflverse publishes parquet/csv per season as
GitHub Release artifacts. One new outbound adapter unlocks every advanced
stat and ATS/O-U trend tool below.

| Tool | Args | Returns |
|---|---|---|
| `get_team_epa` | `team_id, season?, side=off\|def` | EPA/play, pass EPA, rush EPA |
| `get_success_rate` | `team_id, season?` | Offensive + defensive success rate |
| `get_third_down_rate` | `team_id, season?` | 3rd-down conversion %, offense and defense |
| `get_red_zone_efficiency` | `team_id, season?` | RZ TD% (offense + allowed) |
| `get_def_points_per_100_yards` | `team_id, season?` | The sportsbettingstats power stat |
| `get_qb_advanced` | `athlete_id, season?` | CPOE, EPA/play, passer rating, TD:INT |
| `get_ats_record` | `team_id, season?, situation?` | ATS overall + splits (home/away/fav/dog/div/primetime/short-week/post-bye) |
| `get_ou_record` | `team_id, season?` | Over/Under record + splits |
| `get_situational_record` | `team_id, situation` | SU+ATS in arbitrary situation |

### Tier 3 — Open-Meteo adapter (free, no API key)

| Tool | Args | Returns |
|---|---|---|
| `get_game_weather` | `game_id` | Forecast at kickoff: temp, wind, precip — joined via stadium lat/lon. Domes return "indoor". |

### Tier 4 — Live odds (optional; requires free API key)

| Tool | Args | Returns | Source |
|---|---|---|---|
| `get_current_odds` | `game_id` | Spread, ML, total across books | The Odds API (free 500 req/mo, key required) |
| `get_line_movement` | `game_id` | Opening → current | The Odds API |

## Data sources

| Source | Cost | Key? | What it gives you | Notes |
|---|---|---|---|---|
| ESPN site API | free | no | teams, schedule, scoreboard, standings, roster, injuries, news | already in use |
| nflverse-data (GitHub releases) | free | no | play-by-play (EPA, CPOE, success rate), schedules with lines/totals/results, snap counts, rosters, injuries, NGS | best free advanced-stats source — pulls down parquet/csv per season |
| Open-Meteo | free | no | weather forecast/history at lat/lon | for outdoor stadiums; map dome → "indoor" |
| The Odds API | free tier (500 req/mo) | yes | live sportsbook lines + movement | optional; alternative is OddsJam (paid) or scraping |
| DVOA (FTN/Football Outsiders) | paid | n/a | DVOA proper | **skip** — approximate with EPA from nflverse |
| Pro-Football-Reference | free (scrape) | no | deep historical splits | brittle fallback only |

### nflverse details

- Repo: `https://github.com/nflverse/nflverse-data`
- Releases of interest: `pbp` (play-by-play), `schedules` (includes `spread_line`, `total_line`, `result`, `total`), `rosters`, `injuries`, `snap_counts`, `nextgen_stats`
- File format: parquet (preferred) or csv per season
- Recommended access pattern:
  - One outbound adapter responsible for download + on-disk cache (per season, with weekly refresh during the season)
  - In-memory hot cache layered on top via existing `caching_adapter` pattern
  - Read with `pyarrow` (already a transitive dep of many things) or `polars` if preferred for speed

### Open-Meteo details

- Forecast endpoint: `https://api.open-meteo.com/v1/forecast`
- Historical endpoint: `https://archive-api.open-meteo.com/v1/archive`
- No API key, no rate-limit headaches at our volumes
- Need a static stadium → (lat, lon, dome?) lookup table — small, ~32 entries

## Sequencing rationale

1. **Tier 1 first** — pure additions to existing `espn_adapter`, no new
   outbound port; lets us validate the inbound/formatter/service pattern at
   scale before introducing a second data source.
2. **Tier 2 next** — single new outbound adapter for nflverse parquet
   unlocks the highest-value batch (ATS, EPA, red-zone, third-down, the
   "DEF pts/100 yds" power stat) in one shot.
3. **Tier 3** behind a feature flag; small, self-contained.
4. **Tier 4** only if the user is willing to manage an API key.
