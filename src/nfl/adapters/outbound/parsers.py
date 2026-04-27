"""Pure functions that map ESPN JSON wire format into domain models.

Extracted from espn_adapter.py so the adapter focuses on HTTP/transport concerns
while parsing stays a side-effect-free, easily testable concern.
"""

from typing import Any

from ...domain.models import Athlete, Match, MatchCompetitor, NewsItem, PlayerInjury, Standing, Team


def _parse_team(raw: dict[str, Any]) -> Team:
    """Map a raw ESPN team object to a domain Team.

    Args:
        raw: The team dict from the ESPN API (may be nested under "team" key).
    """
    team = raw.get("team", raw)
    logos = team.get("logos", [])
    logo_url = logos[0].get("href") if logos else None
    return Team(
        id=str(team.get("id", "")),
        name=team.get("name", ""),
        abbreviation=team.get("abbreviation", ""),
        location=team.get("location", ""),
        display_name=team.get("displayName", ""),
        logo_url=logo_url,
    )


def _extract_score(raw_score: object) -> str | None:
    """Pull a clean score string out of either ESPN serialization shape.

    The scoreboard endpoint returns `score` as a primitive (e.g. `24`), but other
    endpoints return it as a $ref dict like
    `{'$ref': '...', 'value': 24.0, 'displayValue': '24', 'winner': False}`.
    Prefer `displayValue`, fall back to `value`, and stringify primitives.
    """
    if raw_score is None:
        return None
    if isinstance(raw_score, dict):
        display = raw_score.get("displayValue")
        if display is not None:
            return str(display)
        value = raw_score.get("value")
        return str(int(value)) if isinstance(value, int | float) else None
    return str(raw_score)


def _parse_competitor(raw: dict[str, Any]) -> MatchCompetitor:
    """Map a raw ESPN competitor object to a domain MatchCompetitor."""
    score = raw.get("score")
    winner = raw.get("winner")
    if winner is None and isinstance(score, dict):
        winner = score.get("winner")
    return MatchCompetitor(
        team=_parse_team(raw),
        home_away=raw.get("homeAway", ""),
        score=_extract_score(score),
        winner=bool(winner) if winner is not None else None,
    )


def _parse_match(event: dict[str, Any]) -> Match:
    """Map a raw ESPN scoreboard event to a domain Match."""
    competition = event.get("competitions", [{}])[0]
    status = competition.get("status", {})
    status_type = status.get("type", {})
    competitors = [_parse_competitor(c) for c in competition.get("competitors", [])]
    week_raw = event.get("week") or {}
    week = week_raw.get("number") if isinstance(week_raw, dict) else None
    return Match(
        id=str(event.get("id", "")),
        date=event.get("date", ""),
        name=event.get("name", ""),
        short_name=event.get("shortName", ""),
        status_type=status_type.get("state", ""),
        status_detail=status_type.get("description", status.get("displayClock", "")),
        week=week,
        competitors=competitors,
    )


def _parse_standing(entry: dict[str, Any], conference: str | None, division: str | None) -> Standing | None:
    """Map a raw ESPN standings entry to a domain Standing.

    Args:
        entry: A standings entry dict from the ESPN standings response.
        conference: The "AFC"/"NFC" conference name to attach to the team.
        division: The "East"/"West"/"North"/"South" division to attach to the team.

    Returns None for entries that lack the required team data.
    """
    team_raw = entry.get("team")
    if not team_raw:
        return None

    team = _parse_team(team_raw)
    team.conference = conference
    team.division = division

    stats: dict[str, Any] = {s["name"]: s.get("value", 0) for s in entry.get("stats", [])}
    return Standing(
        team=team,
        wins=int(stats.get("wins", 0)),
        losses=int(stats.get("losses", 0)),
        ties=int(stats.get("ties", 0)),
        win_percent=float(stats.get("winPercent", 0.0)),
        points_for=int(stats.get("pointsFor", 0)),
        points_against=int(stats.get("pointsAgainst", 0)),
        point_differential=int(stats.get("differential", 0)),
    )


def _split_conference_division(name: str) -> tuple[str | None, str | None]:
    """Split an ESPN division name like "AFC East" into ("AFC", "East").

    Returns (None, None) if the name doesn't match the expected shape.
    """
    parts = name.split(" ", 1)
    if len(parts) == 2 and parts[0] in ("AFC", "NFC"):
        return parts[0], parts[1]
    return None, None


def _position_abbreviation(raw: dict[str, Any]) -> str:
    """Extract a position abbreviation from an ESPN athlete payload."""
    position = raw.get("position")
    if isinstance(position, dict):
        return position.get("abbreviation", "")
    return position if isinstance(position, str) else ""


def _parse_athlete(raw: dict[str, Any]) -> Athlete:
    """Map a raw ESPN athlete object to a domain Athlete.

    The team field is populated only when the response embeds a team object.
    """
    team_raw = raw.get("team")
    team = _parse_team(team_raw) if isinstance(team_raw, dict) else None
    return Athlete(
        id=str(raw.get("id", "")),
        full_name=raw.get("fullName", raw.get("displayName", "")),
        position=_position_abbreviation(raw),
        team=team,
        jersey=raw.get("jersey"),
        height=raw.get("displayHeight"),
        weight=raw.get("displayWeight"),
        age=raw.get("age"),
    )


def _parse_player_injury(raw: dict[str, Any], team: Team | None = None) -> PlayerInjury:
    """Map a raw ESPN injury entry to a domain PlayerInjury."""
    athlete = raw.get("athlete", {})
    return PlayerInjury(
        player_name=athlete.get("displayName", athlete.get("fullName", "")),
        position=_position_abbreviation(athlete),
        status=raw.get("status", ""),
        team=team,
        description=raw.get("shortComment") or raw.get("longComment"),
    )


def _parse_news_item(raw: dict[str, Any]) -> NewsItem:
    """Map a raw ESPN news article to a domain NewsItem."""
    links = raw.get("links", {})
    web = links.get("web", {}) if isinstance(links, dict) else {}
    url = web.get("href") if isinstance(web, dict) else None
    return NewsItem(
        headline=raw.get("headline", ""),
        description=raw.get("description", ""),
        published=raw.get("published", ""),
        url=url,
    )
