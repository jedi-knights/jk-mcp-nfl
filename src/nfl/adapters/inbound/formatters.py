"""Plain-text formatters that turn domain objects into LLM-friendly strings.

Kept separate from the MCP adapter so each formatter is a pure function and
trivially unit-testable.
"""

from ...domain.models import Match, Standing, Team


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
