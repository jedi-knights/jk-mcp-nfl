"""Plain-text formatters that turn domain objects into LLM-friendly strings.

Kept separate from the MCP adapter so each formatter is a pure function and
trivially unit-testable.
"""

from ...domain.models import (
    Athlete,
    ATSRecord,
    DefensiveEfficiency,
    EPAStats,
    GameOdds,
    HeadToHead,
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


def _fmt_teams(teams: list[Team]) -> str:
    """Format a list of teams as a numbered text list."""
    if not teams:
        return "No teams found."
    lines = [f"NFL teams ({len(teams)}):"]
    for i, t in enumerate(teams, 1):
        lines.append(f"{i:>2}. {t.display_name} ({t.abbreviation}) — id={t.id}")
    return "\n".join(lines)


def _fmt_team(team: Team) -> str:
    """Format a single team's details."""
    lines = [
        f"{team.display_name} ({team.abbreviation})",
        f"  id:       {team.id}",
        f"  location: {team.location}",
        f"  name:     {team.name}",
    ]
    if team.conference:
        lines.append(f"  division: {team.conference} {team.division or ''}".rstrip())
    if team.logo_url:
        lines.append(f"  logo:     {team.logo_url}")
    return "\n".join(lines)


def _fmt_match(match: Match) -> str:
    """Format a single match as a one-line summary."""
    score = ""
    if match.competitors:
        parts = []
        for c in match.competitors:
            label = c.team.abbreviation or c.team.display_name
            parts.append(f"{label} {c.score}" if c.score is not None else label)
        score = " | " + " vs ".join(parts)
    week = f" [Week {match.week}]" if match.week else ""
    return f"{match.date} — {match.short_name or match.name}{week} — {match.status_detail}{score}"


def _fmt_scoreboard(matches: list[Match]) -> str:
    """Format a list of matches."""
    if not matches:
        return "No NFL games found for that period."
    lines = [f"NFL games ({len(matches)}):"]
    lines.extend(_fmt_match(m) for m in matches)
    return "\n".join(lines)


def _fmt_standings(standings: list[Standing]) -> str:
    """Format the standings as a flat ranked table."""
    if not standings:
        return "No standings available."
    lines = [
        "NFL standings (sorted by win %, then point differential):",
        f"  {'Team':<28} {'W':>2}-{'L':>2}-{'T':>1}  {'Pct':>5}  {'PF':>4}  {'PA':>4}  {'Diff':>5}",
    ]
    for s in standings:
        label = f"{s.team.display_name} ({s.team.abbreviation})"
        diff = f"{s.point_differential:+d}"
        lines.append(
            f"  {label:<28} {s.wins:>2}-{s.losses:>2}-{s.ties:>1}  "
            f"{s.win_percent:>5.3f}  {s.points_for:>4}  {s.points_against:>4}  {diff:>5}"
        )
    return "\n".join(lines)


def _opt(value: float | int | None, fmt: str = "{:.1f}") -> str:
    """Format an optional numeric value, returning 'n/a' when None."""
    return "n/a" if value is None else fmt.format(value)


def _fmt_team_stats(stats: TeamStats) -> str:
    """Format a team's season stats line by line."""
    diff = "n/a" if stats.point_differential is None else f"{stats.point_differential:+d}"
    to_diff = "n/a" if stats.turnover_differential is None else f"{stats.turnover_differential:+d}"
    return "\n".join(
        [
            f"{stats.team.display_name} ({stats.team.abbreviation}) — {stats.season}",
            f"  games:        {stats.games_played}",
            f"  PPG:          {_opt(stats.points_per_game)}",
            f"  YPG allowed:  {_opt(stats.yards_per_game_allowed)}",
            f"  yds/play:     {_opt(stats.yards_per_play, '{:.2f}')}",
            f"  point diff:   {diff}",
            f"  TO diff:      {to_diff}",
        ]
    )


def _fmt_schedule(matches: list[Match]) -> str:
    """Format a team's schedule as a chronological list."""
    if not matches:
        return "No games found in the schedule."
    lines = [f"Schedule ({len(matches)} games):"]
    lines.extend(_fmt_match(m) for m in matches)
    return "\n".join(lines)


def _fmt_head_to_head(h2h: HeadToHead) -> str:
    """Format a head-to-head summary plus the underlying matchups."""
    header = (
        f"{h2h.team_a.display_name} vs {h2h.team_b.display_name}: "
        f"{h2h.team_a_wins}-{h2h.team_b_wins}-{h2h.ties} "
        f"({h2h.team_a.abbreviation} wins-losses-ties)"
    )
    if not h2h.matches:
        return f"{header}\n  No recent matchups in the lookback window."
    lines = [header, f"Recent matchups ({len(h2h.matches)}):"]
    lines.extend(_fmt_match(m) for m in h2h.matches)
    return "\n".join(lines)


def _fmt_roster(roster: list[Athlete]) -> str:
    """Format a team's roster as a numbered list grouped by position."""
    if not roster:
        return "No roster entries found."
    lines = [f"Roster ({len(roster)} players):"]
    for athlete in roster:
        jersey = f" #{athlete.jersey}" if athlete.jersey else ""
        lines.append(f"  {athlete.position:<4}{jersey:<5}  {athlete.full_name}  — id={athlete.id}")
    return "\n".join(lines)


def _fmt_injuries(injuries: list[PlayerInjury]) -> str:
    """Format the injury report."""
    if not injuries:
        return "No injuries reported."
    lines = [f"Injury report ({len(injuries)}):"]
    for injury in injuries:
        team_label = f" [{injury.team.abbreviation}]" if injury.team else ""
        note = f" — {injury.description}" if injury.description else ""
        lines.append(f"  {injury.player_name} ({injury.position}){team_label}: {injury.status}{note}")
    return "\n".join(lines)


def _fmt_athlete(athlete: Athlete) -> str:
    """Format a single athlete's profile."""
    lines = [f"{athlete.full_name} ({athlete.position})  — id={athlete.id}"]
    if athlete.team:
        lines.append(f"  team:    {athlete.team.display_name} ({athlete.team.abbreviation})")
    if athlete.jersey:
        lines.append(f"  jersey:  #{athlete.jersey}")
    if athlete.height:
        lines.append(f"  height:  {athlete.height}")
    if athlete.weight:
        lines.append(f"  weight:  {athlete.weight}")
    if athlete.age is not None:
        lines.append(f"  age:     {athlete.age}")
    return "\n".join(lines)


def _fmt_team_epa(epa: EPAStats) -> str:
    """Format an EPAStats result line by line."""
    return "\n".join(
        [
            f"{epa.team.display_name} ({epa.team.abbreviation}) — {epa.season} — {epa.side} EPA",
            f"  EPA/play:       {epa.epa_per_play:+.3f}",
            f"  Pass EPA/play:  {epa.pass_epa_per_play:+.3f}",
            f"  Rush EPA/play:  {epa.rush_epa_per_play:+.3f}",
            f"  Success rate:   {epa.success_rate:.3f}",
        ]
    )


def _fmt_success_rate(sr: SuccessRate) -> str:
    """Format a SuccessRate as side-by-side offense/defense rates with sample sizes."""
    return "\n".join(
        [
            f"{sr.team.display_name} ({sr.team.abbreviation}) — {sr.season} — Success rate",
            f"  offense: {sr.rate_offense:.3f}  ({sr.plays_offense} plays)",
            f"  defense: {sr.rate_defense:.3f}  ({sr.plays_defense} plays)",
        ]
    )


def _fmt_third_down(td: ThirdDownStats) -> str:
    """Format a ThirdDownStats result for both offense and defense."""
    return "\n".join(
        [
            f"{td.team.display_name} ({td.team.abbreviation}) — {td.season} — Third-down",
            f"  offense: {td.conversions_offense}/{td.attempts_offense} = {td.rate_offense:.3f}",
            f"  defense: {td.conversions_defense_allowed}/{td.attempts_defense} = {td.rate_defense:.3f}",
        ]
    )


def _fmt_red_zone(rz: RedZoneStats) -> str:
    """Format a RedZoneStats result for both offense and defense."""
    return "\n".join(
        [
            f"{rz.team.display_name} ({rz.team.abbreviation}) — {rz.season} — Red zone",
            f"  offense: {rz.touchdowns_offense}/{rz.trips_offense} TDs = {rz.td_rate_offense:.3f}",
            f"  defense: {rz.touchdowns_defense_allowed}/{rz.trips_defense} TDs allowed = {rz.td_rate_defense:.3f}",
        ]
    )


def _fmt_ats_record(record: ATSRecord) -> str:
    """Format an ATS record line."""
    scope = record.situation or "overall"
    return "\n".join(
        [
            f"{record.team.display_name} ({record.team.abbreviation}) — {record.season} — ATS ({scope})",
            f"  W-L-Pushes:  {record.wins}-{record.losses}-{record.pushes}",
        ]
    )


def _fmt_situational_record(record: SituationalRecord) -> str:
    """Format a SituationalRecord with both SU and ATS lines."""
    return "\n".join(
        [
            f"{record.team.display_name} ({record.team.abbreviation}) — {record.season} — {record.situation}",
            f"  SU:   {record.su_wins}-{record.su_losses}-{record.su_ties}",
            f"  ATS:  {record.ats_wins}-{record.ats_losses}-{record.ats_pushes}",
        ]
    )


def _fmt_ou_record(record: OURecord) -> str:
    """Format an Over/Under record line."""
    return "\n".join(
        [
            f"{record.team.display_name} ({record.team.abbreviation}) — {record.season} — Over/Under",
            f"  Overs-Unders-Pushes:  {record.overs}-{record.unders}-{record.pushes}",
        ]
    )


def _fmt_qb_advanced(qb: QBAdvancedStats) -> str:
    """Format an advanced QB stat line."""
    return "\n".join(
        [
            f"{qb.name} — {qb.season} — Advanced QB stats  (athlete_id={qb.athlete_id})",
            f"  Completion %:    {qb.completion_percent:.3f}",
            f"  Yards/attempt:   {qb.yards_per_attempt:.2f}",
            f"  TDs / INTs:      {qb.touchdowns} / {qb.interceptions}  (ratio {qb.td_int_ratio:.2f})",
            f"  Passer rating:   {qb.passer_rating:.1f}",
            f"  CPOE:            {qb.cpoe:+.2f}",
            f"  EPA/play:        {qb.epa_per_play:+.3f}",
        ]
    )


def _fmt_def_points_per_100(de: DefensiveEfficiency) -> str:
    """Format a DefensiveEfficiency power-stat line."""
    return "\n".join(
        [
            f"{de.team.display_name} ({de.team.abbreviation}) — {de.season} — DEF pts/100 yds",
            f"  yards allowed:    {de.yards_allowed}",
            f"  points allowed:   {de.points_allowed}",
            f"  pts per 100 yds:  {de.points_per_100_yards:.3f}",
            f"  rating:           {de.rating}  (good <6.0, average 6.0-7.0, poor >7.0)",
        ]
    )


def _fmt_news(news: list[NewsItem]) -> str:
    """Format a list of news headlines, one block per item."""
    if not news:
        return "No news available."
    blocks = [f"News ({len(news)}):"]
    for item in news:
        block = [f"  {item.headline}", f"    {item.published}"]
        if item.description:
            block.append(f"    {item.description}")
        if item.url:
            block.append(f"    {item.url}")
        blocks.append("\n".join(block))
    return "\n".join(blocks)


def _fmt_odds(odds: list[GameOdds]) -> str:
    """Format a list of GameOdds, one block per game."""
    if not odds:
        return "No live odds available."
    blocks = [f"Live odds ({len(odds)} games):"]
    for entry in odds:
        spread = "n/a" if entry.spread is None else f"{entry.spread:+g}"
        total = "n/a" if entry.total is None else f"{entry.total:g}"
        ml_h = "n/a" if entry.moneyline_home is None else f"{entry.moneyline_home:+d}"
        ml_a = "n/a" if entry.moneyline_away is None else f"{entry.moneyline_away:+d}"
        blocks.append(
            f"  game={entry.game_id}  book={entry.book}  ts={entry.timestamp}\n"
            f"    spread (home): {spread}    total: {total}    ML: home {ml_h} / away {ml_a}"
        )
    return "\n".join(blocks)


def _fmt_weather(weather: Weather) -> str:
    """Format a Weather forecast block. Domes report 'indoor' with no metrics."""
    if weather.is_indoor:
        return f"Game {weather.game_id} — indoor (dome stadium)"
    lines = [f"Game {weather.game_id} — outdoor forecast at kickoff"]
    if weather.temperature_f is not None:
        lines.append(f"  temperature:    {weather.temperature_f:.0f}°F")
    if weather.wind_mph is not None:
        lines.append(f"  wind:           {weather.wind_mph:.0f} mph")
    if weather.precipitation_chance is not None:
        lines.append(f"  precipitation:  {weather.precipitation_chance:.2f} mm")
    if weather.condition:
        lines.append(f"  condition:      {weather.condition}")
    return "\n".join(lines)
