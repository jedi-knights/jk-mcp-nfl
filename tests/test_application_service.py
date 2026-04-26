"""Tests for the application service — input validation and port delegation."""

import pytest

from nfl.application.service import NFLService
from nfl.domain.models import Team


def _team() -> Team:
    return Team(id="12", name="Chiefs", abbreviation="KC", location="Kansas City", display_name="Kansas City Chiefs")


async def test_get_teams_delegates(stub_repo) -> None:
    stub_repo.teams = [_team()]
    service = NFLService(repo=stub_repo)
    result = await service.get_teams()
    assert result == [_team()]
    assert stub_repo.calls == [("get_teams", {})]


async def test_get_team_strips_and_passes_id(stub_repo) -> None:
    stub_repo.team_by_id["12"] = _team()
    service = NFLService(repo=stub_repo)
    await service.get_team("  12  ")
    assert stub_repo.calls == [("get_team", {"team_id": "12"})]


@pytest.mark.parametrize("bad", ["", "   "])
async def test_get_team_rejects_blank(stub_repo, bad: str) -> None:
    service = NFLService(repo=stub_repo)
    with pytest.raises(ValueError):
        await service.get_team(bad)


async def test_get_scoreboard_rejects_malformed_date(stub_repo) -> None:
    service = NFLService(repo=stub_repo)
    with pytest.raises(ValueError):
        await service.get_scoreboard("2026-01-05")


async def test_get_scoreboard_normalizes_date(stub_repo) -> None:
    service = NFLService(repo=stub_repo)
    await service.get_scoreboard("  20260105  ")
    assert stub_repo.calls == [("get_scoreboard", {"date": "20260105"})]


async def test_get_scoreboard_passes_through_none(stub_repo) -> None:
    service = NFLService(repo=stub_repo)
    await service.get_scoreboard()
    assert stub_repo.calls == [("get_scoreboard", {"date": None})]


async def test_get_standings_delegates(stub_repo) -> None:
    service = NFLService(repo=stub_repo)
    await service.get_standings()
    assert stub_repo.calls == [("get_standings", {})]
