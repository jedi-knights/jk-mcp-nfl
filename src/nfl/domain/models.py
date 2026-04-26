"""Domain models for the NFL MCP server.

Pure Python dataclasses with zero framework dependencies. Adapters are
responsible for translating to/from these types from the ESPN API wire format.
"""

from dataclasses import dataclass, field


@dataclass
class Team:
    """An NFL franchise.

    `id` and `abbreviation` are the stable identifiers used by the ESPN API.
    `conference` is "AFC" or "NFC"; `division` is "East", "West", "North", or
    "South". Both are optional because the /teams listing endpoint omits them
    — they're populated by the standings response.
    """

    id: str
    name: str
    abbreviation: str
    location: str
    display_name: str
    conference: str | None = None
    division: str | None = None
    logo_url: str | None = None


@dataclass
class MatchCompetitor:
    """One side of a game — home or away team with its score."""

    team: Team
    home_away: str
    score: str | None = None
    winner: bool | None = None


@dataclass
class Match:
    """A single NFL game (scheduled, in-progress, or completed).

    `status_type` values from the ESPN API:
      "pre"  — scheduled, not yet started
      "in"   — in progress
      "post" — final
    `week` is the regular-season or postseason week number when available.
    """

    id: str
    date: str
    name: str
    short_name: str
    status_type: str
    status_detail: str
    week: int | None = None
    competitors: list[MatchCompetitor] = field(default_factory=list)


@dataclass
class Standing:
    """A team's row in the NFL standings table.

    NFL standings are computed per division, but this model is flat — callers
    can group by `team.conference` / `team.division` if needed. `win_percent`
    is a fraction in [0.0, 1.0]; `point_differential` is `points_for -
    points_against`.
    """

    team: Team
    wins: int
    losses: int
    ties: int
    win_percent: float
    points_for: int
    points_against: int
    point_differential: int
