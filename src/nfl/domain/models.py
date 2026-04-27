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


@dataclass
class TeamStats:
    """Season-level efficiency totals for a team.

    `yards_per_game_allowed` is the YAPG metric called out by handicappers.
    `turnover_differential` is takeaways minus giveaways. The optional fields
    are populated only when the upstream source exposes them; the standings
    endpoint, for example, doesn't carry yardage or turnover data.
    """

    team: Team
    season: int
    games_played: int
    points_per_game: float | None = None
    yards_per_game_allowed: float | None = None
    yards_per_play: float | None = None
    point_differential: int | None = None
    turnover_differential: int | None = None


@dataclass
class ATSRecord:
    """Against-the-spread record, optionally scoped to a situation.

    `situation` is a free-form tag like "home", "away", "favorite",
    "underdog", "divisional", "primetime", "short_week", "post_bye". When
    `None`, the record is the team's overall ATS line for the season.
    """

    team: Team
    season: int
    wins: int
    losses: int
    pushes: int
    situation: str | None = None


@dataclass
class OURecord:
    """Over/Under record for a team's games."""

    team: Team
    season: int
    overs: int
    unders: int
    pushes: int


@dataclass
class SituationalRecord:
    """A team's straight-up and against-the-spread record in a specific situation.

    `situation` is a free-form tag from the supported broader-situational set:
    "vs_winning", "after_loss", "mnf", "tnf", "snf", "dome", "outdoor", etc.
    """

    team: Team
    season: int
    situation: str
    su_wins: int
    su_losses: int
    su_ties: int
    ats_wins: int
    ats_losses: int
    ats_pushes: int


@dataclass
class RedZoneStats:
    """Red zone efficiency, both as the offense and as the defense.

    `td_rate_offense` and `td_rate_defense` are fractions in [0.0, 1.0].
    Handicappers commonly flag `td_rate_offense >= 0.60` as a strong offense.
    """

    team: Team
    season: int
    trips_offense: int
    touchdowns_offense: int
    td_rate_offense: float
    trips_defense: int
    touchdowns_defense_allowed: int
    td_rate_defense: float


@dataclass
class ThirdDownStats:
    """Third-down conversion rates as offense and defense.

    Rates are fractions in [0.0, 1.0].
    """

    team: Team
    season: int
    attempts_offense: int
    conversions_offense: int
    rate_offense: float
    attempts_defense: int
    conversions_defense_allowed: int
    rate_defense: float


@dataclass
class EPAStats:
    """Expected Points Added per play for one side of the ball.

    `side` is "offense" or "defense". For defense, more-negative EPA/play is
    better (the defense is preventing expected points).
    """

    team: Team
    season: int
    side: str
    epa_per_play: float
    pass_epa_per_play: float
    rush_epa_per_play: float
    success_rate: float


@dataclass
class SuccessRate:
    """A team's offensive and defensive success rates side-by-side.

    Success rate is the share of plays that meet a down-and-distance success
    threshold (typically EPA-positive). The companion fields provide the play
    counts so callers can judge sample size.
    """

    team: Team
    season: int
    rate_offense: float
    rate_defense: float
    plays_offense: int
    plays_defense: int


@dataclass
class QBAdvancedStats:
    """Quarterback efficiency metrics combining traditional and advanced stats.

    `cpoe` is Completion Percentage Over Expected (nflverse). `passer_rating`
    is the NFL's 0–158.3 formula.
    """

    athlete_id: str
    name: str
    season: int
    completion_percent: float
    yards_per_attempt: float
    touchdowns: int
    interceptions: int
    td_int_ratio: float
    passer_rating: float
    cpoe: float
    epa_per_play: float


@dataclass
class DefensiveEfficiency:
    """The "Defensive Points per 100 Yards" power stat.

    Formula: `(yards_allowed / 100) / points_allowed`. The bands cited by
    sportsbettingstats.com: <6.0 "good", 6.0–7.0 "average", >7.0 "poor".
    `rating` is one of those three labels.
    """

    team: Team
    season: int
    yards_allowed: int
    points_allowed: int
    points_per_100_yards: float
    rating: str


@dataclass
class Weather:
    """Weather conditions at kickoff for a single game.

    For dome stadiums, `is_indoor` is True and the metric fields are `None`.
    For outdoor stadiums, the metric fields are populated from a forecast
    (future games) or historical observation (past games).
    """

    game_id: str
    is_indoor: bool
    temperature_f: float | None = None
    wind_mph: float | None = None
    precipitation_chance: float | None = None
    condition: str | None = None


@dataclass
class GameOdds:
    """A single sportsbook's line for a game at a point in time.

    `spread` is from the home team's perspective (negative means home is
    favored). `total` is the over/under combined score. American odds for
    moneylines.
    """

    game_id: str
    book: str
    timestamp: str
    spread: float | None = None
    moneyline_home: int | None = None
    moneyline_away: int | None = None
    total: float | None = None


@dataclass
class PlayerInjury:
    """A player's listing on the weekly injury report."""

    player_name: str
    position: str
    status: str
    team: Team | None = None
    description: str | None = None


@dataclass
class NewsItem:
    """A news headline associated with a team or the league."""

    headline: str
    description: str
    published: str
    url: str | None = None


@dataclass
class Athlete:
    """An NFL player's identity and basic profile.

    Statistical detail lives in dedicated stat models (e.g. `QBAdvancedStats`).
    """

    id: str
    full_name: str
    position: str
    team: Team | None = None
    jersey: str | None = None
    height: str | None = None
    weight: str | None = None
    age: int | None = None


@dataclass
class HeadToHead:
    """Aggregated record between two teams across a span of matchups."""

    team_a: Team
    team_b: Team
    team_a_wins: int
    team_b_wins: int
    ties: int
    matches: list[Match] = field(default_factory=list)
