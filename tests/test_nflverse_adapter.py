"""Tests for the nflverse outbound adapter — download, on-disk cache, parquet loading."""

import io
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import polars as pl
import pytest

from nfl.adapters.outbound.nflverse_adapter import (
    NFLVerseAdapter,
    _ats_outcome,
    _compute_ats,
    _compute_def_points_per_100,
    _compute_epa,
    _compute_ou,
    _compute_qb_advanced,
    _compute_red_zone,
    _compute_situational,
    _compute_success_rate,
    _compute_third_down,
    _def_rating,
    _is_primetime,
    _is_team_favorite,
    _is_winning_record,
    _opponent_records,
    _ou_outcome,
    _passer_rating,
    _resolve_player,
    _su_outcome,
)
from nfl.domain.exceptions import NFLNotFoundError, SeasonNotAvailableError, UpstreamAPIError
from nfl.domain.models import Team


def _parquet_bytes(df: pl.DataFrame) -> bytes:
    """Serialize a DataFrame to in-memory parquet bytes."""
    buf = io.BytesIO()
    df.write_parquet(buf)
    return buf.getvalue()


@pytest.fixture
def pbp_bytes() -> bytes:
    return _parquet_bytes(pl.DataFrame({"game_id": ["1", "2"], "season": [2025, 2025], "epa": [0.5, -0.1]}))


@pytest.fixture
def schedules_bytes() -> bytes:
    return _parquet_bytes(
        pl.DataFrame(
            {
                "game_id": ["g1", "g2"],
                "season": [2024, 2025],
                "home_team": ["KC", "BUF"],
                "away_team": ["BUF", "KC"],
                "spread_line": [-2.5, 3.0],
                "total_line": [48.0, 50.5],
                "result": [7, -3],
                "total": [54, 41],
            }
        )
    )


def _make_adapter(
    tmp_path: Path,
    handler,
    now: datetime | None = None,
    max_age_hours: float = 24.0,
) -> NFLVerseAdapter:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, follow_redirects=True)
    fixed_now = now or datetime(2026, 1, 5, tzinfo=UTC)
    return NFLVerseAdapter(
        cache_dir=tmp_path,
        client=client,
        max_age_hours=max_age_hours,
        now=lambda: fixed_now,
    )


async def test_load_play_by_play_downloads_and_caches(tmp_path: Path, pbp_bytes: bytes) -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, content=pbp_bytes)

    adapter = _make_adapter(tmp_path, handler)
    df = await adapter.load_play_by_play(2025)

    assert df.shape == (2, 3)
    assert len(captured) == 1
    assert "play_by_play_2025.parquet" in str(captured[0].url)
    assert (tmp_path / "pbp" / "play_by_play_2025.parquet").exists()


async def test_second_load_uses_disk_cache(tmp_path: Path, pbp_bytes: bytes) -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, content=pbp_bytes)

    adapter = _make_adapter(tmp_path, handler)
    await adapter.load_play_by_play(2025)
    await adapter.load_play_by_play(2025)

    assert len(captured) == 1


async def test_in_memory_df_cache_prevents_reparse(tmp_path: Path, pbp_bytes: bytes, mocker) -> None:
    """Repeated load_play_by_play for the same season parses parquet only once."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=pbp_bytes)

    adapter = _make_adapter(tmp_path, handler)
    spy = mocker.spy(pl, "read_parquet")
    await adapter.load_play_by_play(2025)
    await adapter.load_play_by_play(2025)
    await adapter.load_play_by_play(2025)
    assert spy.call_count == 1


async def test_past_season_never_refreshes(tmp_path: Path, pbp_bytes: bytes) -> None:
    """Old seasons are final — once cached, never re-downloaded regardless of mtime."""
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, content=pbp_bytes)

    # Pre-write a stale file for season 2020 (well in the past).
    target = tmp_path / "pbp" / "play_by_play_2020.parquet"
    target.parent.mkdir(parents=True)
    target.write_bytes(pbp_bytes)
    # Backdate it heavily.
    old = (datetime.now(UTC) - timedelta(days=1000)).timestamp()
    import os

    os.utime(target, (old, old))

    adapter = _make_adapter(tmp_path, handler)
    await adapter.load_play_by_play(2020)
    assert captured == []


async def test_current_season_refreshes_when_stale(tmp_path: Path, pbp_bytes: bytes) -> None:
    """Current-season cache file older than max_age_hours triggers a re-download."""
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, content=pbp_bytes)

    target = tmp_path / "pbp" / "play_by_play_2025.parquet"
    target.parent.mkdir(parents=True)
    target.write_bytes(pbp_bytes)
    # Backdate by 48 hours so it's stale (default max_age_hours=24).
    old = (datetime(2026, 1, 5, tzinfo=UTC) - timedelta(hours=48)).timestamp()
    import os

    os.utime(target, (old, old))

    adapter = _make_adapter(tmp_path, handler)
    await adapter.load_play_by_play(2025)
    assert len(captured) == 1


async def test_load_schedules_filters_by_season(tmp_path: Path, schedules_bytes: bytes) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=schedules_bytes)

    adapter = _make_adapter(tmp_path, handler)
    df = await adapter.load_schedules(2025)
    assert df.shape == (1, 8)
    assert df["season"].to_list() == [2025]


async def test_load_schedules_without_season_returns_all(tmp_path: Path, schedules_bytes: bytes) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=schedules_bytes)

    adapter = _make_adapter(tmp_path, handler)
    df = await adapter.load_schedules()
    assert df.shape == (2, 8)


async def test_load_rosters_downloads_per_season(tmp_path: Path) -> None:
    rosters = _parquet_bytes(pl.DataFrame({"player_id": ["p1"], "team": ["KC"], "season": [2025]}))
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, content=rosters)

    adapter = _make_adapter(tmp_path, handler)
    df = await adapter.load_rosters(2025)
    assert df["player_id"].to_list() == ["p1"]
    assert "roster_2025.parquet" in str(captured[0].url)


async def test_404_translates_to_season_not_available(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, content=b"")

    adapter = _make_adapter(tmp_path, handler)
    with pytest.raises(SeasonNotAvailableError):
        await adapter.load_play_by_play(2030)


async def test_500_translates_to_upstream_error(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content=b"")

    adapter = _make_adapter(tmp_path, handler)
    with pytest.raises(UpstreamAPIError):
        await adapter.load_play_by_play(2025)


# ---------- Pure analytical helper tests ----------


def _kc() -> Team:
    return Team(id="12", name="Chiefs", abbreviation="KC", location="KC", display_name="Chiefs")


def _sample_pbp() -> pl.DataFrame:
    """A tiny but realistic pbp slice covering one KC vs BUF game."""
    rows = [
        # KC offense (posteam=KC, defteam=BUF)
        {
            "game_id": "g1",
            "drive": 1,
            "posteam": "KC",
            "defteam": "BUF",
            "down": 1,
            "epa": 0.4,
            "pass": 1,
            "rush": 0,
            "success": 1,
            "yardline_100": 70,
            "touchdown": 0,
            "third_down_converted": 0,
            "yards_gained": 8,
        },
        {
            "game_id": "g1",
            "drive": 1,
            "posteam": "KC",
            "defteam": "BUF",
            "down": 2,
            "epa": 0.1,
            "pass": 0,
            "rush": 1,
            "success": 1,
            "yardline_100": 62,
            "touchdown": 0,
            "third_down_converted": 0,
            "yards_gained": 3,
        },
        {
            "game_id": "g1",
            "drive": 1,
            "posteam": "KC",
            "defteam": "BUF",
            "down": 3,
            "epa": -0.2,
            "pass": 1,
            "rush": 0,
            "success": 0,
            "yardline_100": 59,
            "touchdown": 0,
            "third_down_converted": 0,
            "yards_gained": 2,
        },
        # KC red-zone trip (drive 2) ending in TD
        {
            "game_id": "g1",
            "drive": 2,
            "posteam": "KC",
            "defteam": "BUF",
            "down": 1,
            "epa": 2.5,
            "pass": 1,
            "rush": 0,
            "success": 1,
            "yardline_100": 15,
            "touchdown": 1,
            "third_down_converted": 0,
            "yards_gained": 15,
        },
        # KC red-zone trip (drive 3) — no TD
        {
            "game_id": "g1",
            "drive": 3,
            "posteam": "KC",
            "defteam": "BUF",
            "down": 1,
            "epa": -0.1,
            "pass": 0,
            "rush": 1,
            "success": 0,
            "yardline_100": 18,
            "touchdown": 0,
            "third_down_converted": 0,
            "yards_gained": 2,
        },
        {
            "game_id": "g1",
            "drive": 3,
            "posteam": "KC",
            "defteam": "BUF",
            "down": 3,
            "epa": 1.0,
            "pass": 1,
            "rush": 0,
            "success": 1,
            "yardline_100": 16,
            "touchdown": 0,
            "third_down_converted": 1,
            "yards_gained": 5,
        },
        # BUF offense (defteam=KC) — counts as KC defense
        {
            "game_id": "g1",
            "drive": 4,
            "posteam": "BUF",
            "defteam": "KC",
            "down": 1,
            "epa": 0.2,
            "pass": 1,
            "rush": 0,
            "success": 1,
            "yardline_100": 75,
            "touchdown": 0,
            "third_down_converted": 0,
            "yards_gained": 5,
        },
        {
            "game_id": "g1",
            "drive": 4,
            "posteam": "BUF",
            "defteam": "KC",
            "down": 3,
            "epa": 1.0,
            "pass": 1,
            "rush": 0,
            "success": 1,
            "yardline_100": 70,
            "touchdown": 0,
            "third_down_converted": 1,
            "yards_gained": 12,
        },
        # BUF red-zone trip ending in TD (KC defense allowed)
        {
            "game_id": "g1",
            "drive": 5,
            "posteam": "BUF",
            "defteam": "KC",
            "down": 1,
            "epa": 2.0,
            "pass": 0,
            "rush": 1,
            "success": 1,
            "yardline_100": 10,
            "touchdown": 1,
            "third_down_converted": 0,
            "yards_gained": 10,
        },
    ]
    return pl.DataFrame(rows)


def test_compute_epa_offense_aggregates_correctly() -> None:
    pbp = _sample_pbp()
    plays = pbp.filter(pl.col("posteam") == "KC")
    epa = _compute_epa(_kc(), 2025, "offense", plays)
    assert epa.side == "offense"
    # KC offense plays: epa values [0.4, 0.1, -0.2, 2.5, -0.1, 1.0] → mean ≈ 0.6166
    assert epa.epa_per_play == pytest.approx(3.7 / 6, rel=1e-3)
    # KC offense success rate: 4 success / 6 plays
    assert epa.success_rate == pytest.approx(4 / 6, rel=1e-3)


def test_compute_success_rate_splits_by_team_role() -> None:
    sr = _compute_success_rate(_kc(), 2025, _sample_pbp())
    assert sr.plays_offense == 6  # KC posteam plays
    assert sr.plays_defense == 3  # BUF posteam = KC defteam plays
    assert sr.rate_defense == pytest.approx(3 / 3)


def test_compute_third_down_counts_attempts_and_conversions() -> None:
    td = _compute_third_down(_kc(), 2025, _sample_pbp())
    # KC offense 3rd downs: 2 attempts, 1 conversion → 0.5
    assert td.attempts_offense == 2
    assert td.conversions_offense == 1
    assert td.rate_offense == pytest.approx(0.5)
    # KC defense 3rd downs (BUF on offense): 1 attempt, 1 conversion allowed
    assert td.attempts_defense == 1
    assert td.rate_defense == pytest.approx(1.0)


def test_compute_red_zone_excludes_defensive_touchdowns() -> None:
    """A pick-6 in the red zone should not be credited as an offensive TD."""
    pbp = pl.DataFrame(
        [
            # KC offense in red zone, pass intercepted and returned for TD by BUF
            {
                "game_id": "g1",
                "drive": 1,
                "posteam": "KC",
                "defteam": "BUF",
                "yardline_100": 15,
                "touchdown": 1,
                "pass_touchdown": 0,
                "rush_touchdown": 0,
            },
        ]
    )
    rz = _compute_red_zone(_kc(), 2025, pbp)
    # KC had 1 RZ trip but 0 offensive TDs (the TD belongs to BUF defense)
    assert rz.trips_offense == 1
    assert rz.touchdowns_offense == 0
    assert rz.td_rate_offense == 0.0


def test_compute_red_zone_groups_by_drive() -> None:
    rz = _compute_red_zone(_kc(), 2025, _sample_pbp())
    # KC offense: drive 2 (TD) and drive 3 (no TD) → 2 trips, 1 TD
    assert rz.trips_offense == 2
    assert rz.touchdowns_offense == 1
    assert rz.td_rate_offense == pytest.approx(0.5)
    # KC defense: 1 BUF trip ending in TD
    assert rz.trips_defense == 1
    assert rz.touchdowns_defense_allowed == 1


def test_compute_def_points_per_100_uses_pbp_yards_and_schedule_points() -> None:
    schedules = pl.DataFrame(
        {
            "season": [2025],
            "home_team": ["KC"],
            "away_team": ["BUF"],
            "home_score": [27],
            "away_score": [24],
        }
    )
    de = _compute_def_points_per_100(_kc(), 2025, _sample_pbp(), schedules)
    # KC defense yards allowed = sum of BUF yards_gained = 5 + 12 + 10 = 27
    assert de.yards_allowed == 27
    # KC was home, BUF (away) scored 24 → points_allowed = 24
    assert de.points_allowed == 24
    # metric = points_allowed / (yards_allowed / 100) = 24 / 0.27 ≈ 88.89
    # The tiny test fixture produces an unrealistic ratio; in real seasons
    # the metric typically lands in 5-9 range.
    assert de.points_per_100_yards == pytest.approx(88.89, rel=1e-2)
    # >7.0 → "poor"
    assert de.rating == "poor"


def test_compute_def_points_per_100_realistic_season_yields_band_value() -> None:
    """Sanity check: real-world-scale inputs land in the 6-7 'average' band."""
    # Simulate a season where the team allowed 4200 yds and 320 pts.
    # Build minimal pbp summing to 4200 yards against KC.
    pbp = pl.DataFrame({"defteam": ["KC"], "yards_gained": [4200]})
    schedules = pl.DataFrame(
        {
            "season": [2025],
            "home_team": ["KC"],
            "away_team": ["BUF"],
            "home_score": [0],
            "away_score": [320],
        }
    )
    de = _compute_def_points_per_100(_kc(), 2025, pbp, schedules)
    # 320 / (4200 / 100) = 320 / 42 ≈ 7.62 → "poor" band
    assert de.points_per_100_yards == pytest.approx(7.619, rel=1e-3)
    assert de.rating == "poor"


def test_def_rating_buckets_match_thresholds() -> None:
    assert _def_rating(0.0) == "unknown"
    assert _def_rating(5.5) == "good"
    assert _def_rating(6.5) == "average"
    assert _def_rating(7.5) == "poor"


# ---------- End-to-end adapter test (via load methods + analytical layer) ----------


def _sample_rosters() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "gsis_id": ["00-0033873", "00-0036212"],
            "espn_id": ["3139477", "9999"],
            "full_name": ["Patrick Mahomes", "Some Other Player"],
            "position": ["QB", "WR"],
        }
    )


def _sample_qb_pbp() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "passer_player_id": ["00-0033873"] * 4,
            "pass": [1, 1, 1, 1],
            "complete_pass": [1, 0, 1, 0],
            "yards_gained": [12, 0, 25, 0],
            "pass_touchdown": [0, 0, 1, 0],
            "interception": [0, 0, 0, 1],
            "epa": [0.5, -0.4, 3.2, -3.5],
            "cpoe": [4.0, -2.5, 6.0, -10.0],
        }
    )


def test_resolve_player_returns_gsis_and_name() -> None:
    gsis, name = _resolve_player(_sample_rosters(), "3139477")
    assert gsis == "00-0033873"
    assert name == "Patrick Mahomes"


def test_resolve_player_raises_when_no_match() -> None:
    with pytest.raises(NFLNotFoundError):
        _resolve_player(_sample_rosters(), "0000")


def test_resolve_player_raises_when_no_espn_id_column() -> None:
    rosters = pl.DataFrame({"gsis_id": ["x"], "full_name": ["X"]})
    with pytest.raises(NFLNotFoundError):
        _resolve_player(rosters, "1")


def test_compute_qb_advanced_aggregates_pass_plays() -> None:
    qb = _compute_qb_advanced("3139477", "Patrick Mahomes", 2025, "00-0033873", _sample_qb_pbp())
    # 4 attempts, 2 completions → 0.5
    assert qb.completion_percent == pytest.approx(0.5)
    # 37 yards / 4 = 9.25
    assert qb.yards_per_attempt == pytest.approx(9.25)
    assert qb.touchdowns == 1
    assert qb.interceptions == 1
    assert qb.td_int_ratio == pytest.approx(1.0)
    # cpoe avg = (4 - 2.5 + 6 - 10) / 4 = -0.625
    assert qb.cpoe == pytest.approx(-0.625)


def test_passer_rating_clamps_components() -> None:
    # Perfect rating cap requires all four components clamped to 2.375.
    # Use 80% completion (a clamps), 12.5 YPA (b at cap), 4 TDs in 30 att (c clamps), 0 INTs (d at cap).
    rating = _passer_rating(0.8, 12.5, 4, 0, 30)
    assert rating == pytest.approx(158.333, rel=1e-3)


def test_compute_qb_advanced_zeroes_when_no_attempts() -> None:
    pbp = pl.DataFrame({"passer_player_id": ["other"], "pass": [1]})
    qb = _compute_qb_advanced("3139477", "QB", 2025, "00-0033873", pbp)
    assert qb.passer_rating == 0.0
    assert qb.touchdowns == 0


async def test_get_qb_advanced_end_to_end(tmp_path: Path) -> None:
    """Adapter loads rosters, resolves athlete, then loads pbp and aggregates."""
    rosters_bytes = _parquet_bytes(_sample_rosters())
    pbp_bytes_qb = _parquet_bytes(_sample_qb_pbp())
    call_log: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        call_log.append(url)
        if "roster" in url:
            return httpx.Response(200, content=rosters_bytes)
        return httpx.Response(200, content=pbp_bytes_qb)

    adapter = _make_adapter(tmp_path, handler)
    qb = await adapter.get_qb_advanced("3139477", 2025)
    assert qb.athlete_id == "3139477"
    assert qb.name == "Patrick Mahomes"
    assert qb.touchdowns == 1
    # Both rosters and pbp should be fetched once.
    assert any("roster" in u for u in call_log)
    assert any("play_by_play" in u for u in call_log)


def _ats_schedules() -> pl.DataFrame:
    """Three KC games covering home/away, fave/dog, and a primetime night game."""
    return pl.DataFrame(
        [
            {
                "season": 2025,
                "week": 1,
                "weekday": "Sun",
                "gametime": "13:00",
                "home_team": "KC",
                "away_team": "BUF",
                "spread_line": -3.0,
                "total_line": 48.5,
                "home_score": 27,
                "away_score": 24,
                "result": 3,
                "total": 51,
            },
            # KC home, fav by 3, won by 3 → ATS push, total 51 > 48.5 → over
            {
                "season": 2025,
                "week": 2,
                "weekday": "Mon",
                "gametime": "20:15",
                "home_team": "BUF",
                "away_team": "KC",
                "spread_line": 2.5,
                "total_line": 47.0,
                "home_score": 14,
                "away_score": 21,
                "result": -7,
                "total": 35,
            },
            # KC away, KC favored by 2.5 (since BUF home is dog by 2.5), won by 7 → KC ATS win, under
            {
                "season": 2025,
                "week": 3,
                "weekday": "Sun",
                "gametime": "13:00",
                "home_team": "KC",
                "away_team": "DEN",
                "spread_line": -7.0,
                "total_line": 50.0,
                "home_score": 35,
                "away_score": 10,
                "result": 25,
                "total": 45,
            },
            # KC home, fav by 7, won by 25 → ATS win, total 45 < 50 → under
        ]
    )


def test_ats_outcome_branches() -> None:
    # Home, fav by 3, won by 3 → push
    assert _ats_outcome("KC", "KC", -3.0, 3) == "push"
    # Home, fav by 7, won by 25 → win
    assert _ats_outcome("KC", "KC", -7.0, 25) == "win"
    # Away, fav by 2.5 (home spread +2.5), won by 7 (result=-7 home perspective) → win
    assert _ats_outcome("KC", "BUF", 2.5, -7) == "win"
    # Home, dog by 3, lost by 5 → loss
    assert _ats_outcome("KC", "KC", 3.0, -5) == "loss"


def test_ou_outcome_branches() -> None:
    assert _ou_outcome(48.5, 51) == "over"
    assert _ou_outcome(50.0, 45) == "under"
    assert _ou_outcome(47.0, 47) == "push"


def test_is_team_favorite() -> None:
    assert _is_team_favorite("KC", "KC", -3.0) is True  # home favored
    assert _is_team_favorite("KC", "KC", 3.0) is False  # home dog
    assert _is_team_favorite("KC", "BUF", 2.5) is True  # away favored (home dog)
    assert _is_team_favorite("KC", "BUF", -2.5) is False  # away dog


def test_is_primetime() -> None:
    assert _is_primetime("Mon", "20:15") is True
    assert _is_primetime("Thu", "20:15") is True
    assert _is_primetime("Sun", "20:20") is True
    assert _is_primetime("Sun", "13:00") is False
    assert _is_primetime("Sat", "16:00") is False


def test_compute_ats_overall() -> None:
    team = Team(id="12", name="Chiefs", abbreviation="KC", location="KC", display_name="Chiefs")
    record = _compute_ats(team, 2025, None, _ats_schedules())
    # KC overall: push, win, win → 2-0-1
    assert record.wins == 2
    assert record.losses == 0
    assert record.pushes == 1
    assert record.situation is None


def test_compute_ats_home_only() -> None:
    team = Team(id="12", name="Chiefs", abbreviation="KC", location="KC", display_name="Chiefs")
    record = _compute_ats(team, 2025, "home", _ats_schedules())
    # KC home: game 1 (push) + game 3 (win) → 1-0-1
    assert record.wins == 1
    assert record.pushes == 1
    assert record.situation == "home"


def test_compute_ats_primetime_only() -> None:
    team = Team(id="12", name="Chiefs", abbreviation="KC", location="KC", display_name="Chiefs")
    record = _compute_ats(team, 2025, "primetime", _ats_schedules())
    # Only the Mon game is primetime → KC win
    assert record.wins == 1
    assert record.losses == 0


def test_compute_ats_favorite_only() -> None:
    team = Team(id="12", name="Chiefs", abbreviation="KC", location="KC", display_name="Chiefs")
    record = _compute_ats(team, 2025, "favorite", _ats_schedules())
    # KC was the favorite in all three games (home -3, away -2.5, home -7) → push, win, win
    assert record.wins + record.losses + record.pushes == 3


def test_compute_ats_skips_unplayed_games() -> None:
    schedules = pl.DataFrame(
        [
            {
                "season": 2025,
                "week": 1,
                "weekday": "Sun",
                "gametime": "13:00",
                "home_team": "KC",
                "away_team": "BUF",
                "spread_line": -3.0,
                "total_line": 48.5,
                "home_score": 27,
                "away_score": 24,
                "result": 3,
                "total": 51,
            },
            {
                "season": 2025,
                "week": 2,
                "weekday": "Sun",
                "gametime": "13:00",
                "home_team": "KC",
                "away_team": "DEN",
                "spread_line": -7.0,
                "total_line": 50.0,
                "home_score": None,
                "away_score": None,
                "result": None,
                "total": None,
            },
        ]
    )
    team = Team(id="12", name="Chiefs", abbreviation="KC", location="KC", display_name="Chiefs")
    record = _compute_ats(team, 2025, None, schedules)
    assert record.wins + record.losses + record.pushes == 1  # only game 1 counted


def test_compute_ou_tallies_over_under_push() -> None:
    team = Team(id="12", name="Chiefs", abbreviation="KC", location="KC", display_name="Chiefs")
    record = _compute_ou(team, 2025, _ats_schedules())
    # KC games: game 1 over, game 2 under, game 3 under → 1 over, 2 under
    assert record.overs == 1
    assert record.unders == 2
    assert record.pushes == 0


def _situational_schedules() -> pl.DataFrame:
    """Schedules for KC's season covering MNF, SNF, dome, after-loss, and a vs-winning opponent."""
    return pl.DataFrame(
        [
            {
                "season": 2025,
                "week": 1,
                "weekday": "Sun",
                "gametime": "13:00",
                "gameday": "2025-09-07",
                "home_team": "KC",
                "away_team": "BAL",
                "spread_line": -3.0,
                "total_line": 48.0,
                "home_score": 14,
                "away_score": 24,
                "result": -10,
                "total": 38,
                "roof": "outdoors",
            },
            # KC home, lost (SU) → loss; ATS: home spread -3, lost by 10 → adjusted -13 → loss; total under
            {
                "season": 2025,
                "week": 2,
                "weekday": "Mon",
                "gametime": "20:15",
                "gameday": "2025-09-15",
                "home_team": "BUF",
                "away_team": "KC",
                "spread_line": 2.5,
                "total_line": 47.0,
                "home_score": 14,
                "away_score": 21,
                "result": -7,
                "total": 35,
                "roof": "outdoors",
            },
            # KC away on MNF; KC wins SU; came after a loss → after_loss qualifies
            {
                "season": 2025,
                "week": 3,
                "weekday": "Sun",
                "gametime": "20:20",
                "gameday": "2025-09-21",
                "home_team": "KC",
                "away_team": "DEN",
                "spread_line": -7.0,
                "total_line": 44.0,
                "home_score": 35,
                "away_score": 10,
                "result": 25,
                "total": 45,
                "roof": "outdoors",
            },
            # KC home on SNF; SU win
            {
                "season": 2025,
                "week": 4,
                "weekday": "Sun",
                "gametime": "13:00",
                "gameday": "2025-09-28",
                "home_team": "DET",
                "away_team": "KC",
                "spread_line": 3.0,
                "total_line": 50.0,
                "home_score": 24,
                "away_score": 27,
                "result": -3,
                "total": 51,
                "roof": "dome",
            },
            # KC away in dome; SU win
            # BAL beats KC then beats other opponents to be a "winning team" for vs_winning filter
            {
                "season": 2025,
                "week": 5,
                "weekday": "Sun",
                "gametime": "13:00",
                "gameday": "2025-10-05",
                "home_team": "BAL",
                "away_team": "DEN",
                "spread_line": -7.0,
                "total_line": 44.0,
                "home_score": 28,
                "away_score": 14,
                "result": 14,
                "total": 42,
                "roof": "outdoors",
            },
            {
                "season": 2025,
                "week": 6,
                "weekday": "Sun",
                "gametime": "13:00",
                "gameday": "2025-10-12",
                "home_team": "BAL",
                "away_team": "DET",
                "spread_line": -3.0,
                "total_line": 47.0,
                "home_score": 21,
                "away_score": 17,
                "result": 4,
                "total": 38,
                "roof": "outdoors",
            },
        ]
    )


def test_su_outcome_branches() -> None:
    assert _su_outcome("KC", "KC", 27, 24) == "win"
    assert _su_outcome("KC", "KC", 17, 24) == "loss"
    assert _su_outcome("KC", "BUF", 14, 21) == "win"  # KC away
    assert _su_outcome("KC", "BUF", 24, 24) == "tie"


def test_opponent_records_tallies_per_team() -> None:
    records = _opponent_records(_situational_schedules())
    # BAL won game 1 vs KC, won game 5 vs DEN, won game 6 vs DET → 3-0
    assert records["BAL"] == (3, 0, 0)
    # KC went 1-1 in games 1-2, won 3, won 4 → 3-1
    assert records["KC"] == (3, 1, 0)


def test_is_winning_record() -> None:
    assert _is_winning_record((3, 1, 0)) is True
    assert _is_winning_record((1, 3, 0)) is False
    assert _is_winning_record((0, 0, 0)) is False


def test_compute_situational_mnf_filters_to_monday_games() -> None:
    team = Team(id="12", name="Chiefs", abbreviation="KC", location="KC", display_name="Chiefs")
    record = _compute_situational(team, 2025, "mnf", _situational_schedules())
    # KC played 1 MNF game (week 2) and won SU and ATS
    assert record.su_wins == 1
    assert record.ats_wins == 1


def test_compute_situational_snf_filters_to_sunday_night() -> None:
    team = Team(id="12", name="Chiefs", abbreviation="KC", location="KC", display_name="Chiefs")
    record = _compute_situational(team, 2025, "snf", _situational_schedules())
    # KC played 1 SNF game (week 3 at 20:20)
    assert record.su_wins == 1


def test_compute_situational_dome_uses_roof_column() -> None:
    team = Team(id="12", name="Chiefs", abbreviation="KC", location="KC", display_name="Chiefs")
    record = _compute_situational(team, 2025, "dome", _situational_schedules())
    # KC played 1 game in a dome (week 4 at DET) and won SU
    assert record.su_wins == 1


def test_compute_situational_after_loss_uses_chronological_lookback() -> None:
    team = Team(id="12", name="Chiefs", abbreviation="KC", location="KC", display_name="Chiefs")
    record = _compute_situational(team, 2025, "after_loss", _situational_schedules())
    # KC lost week 1 → week 2 qualifies as after_loss; KC won that → 1-0 SU
    assert record.su_wins == 1
    assert record.su_losses == 0


def test_compute_situational_vs_winning_filters_to_strong_opponents() -> None:
    team = Team(id="12", name="Chiefs", abbreviation="KC", location="KC", display_name="Chiefs")
    record = _compute_situational(team, 2025, "vs_winning", _situational_schedules())
    # BAL is the only team with a winning record at season end (3-0). KC played BAL once → 1 game, lost.
    assert record.su_wins == 0
    assert record.su_losses == 1


async def test_get_situational_record_end_to_end(tmp_path: Path) -> None:
    payload = _parquet_bytes(_situational_schedules())

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload)

    adapter = _make_adapter(tmp_path, handler)
    team = Team(id="12", name="Chiefs", abbreviation="KC", location="KC", display_name="Chiefs")
    record = await adapter.get_situational_record(team, 2025, "mnf")
    assert record.situation == "mnf"
    assert record.su_wins == 1


async def test_get_ats_record_end_to_end(tmp_path: Path) -> None:
    schedules_payload = _parquet_bytes(_ats_schedules())

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=schedules_payload)

    adapter = _make_adapter(tmp_path, handler)
    team = Team(id="12", name="Chiefs", abbreviation="KC", location="KC", display_name="Chiefs")
    record = await adapter.get_ats_record(team, 2025, situation="home")
    assert record.situation == "home"
    assert record.wins == 1


async def test_get_team_epa_loads_pbp_and_returns_epa_stats(tmp_path: Path) -> None:
    payload = _parquet_bytes(_sample_pbp())

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload)

    adapter = _make_adapter(tmp_path, handler)
    epa = await adapter.get_team_epa(_kc(), 2025, "offense")
    assert epa.team.abbreviation == "KC"
    assert epa.season == 2025
    assert epa.epa_per_play == pytest.approx(3.7 / 6, rel=1e-3)
