"""Tests for the Open-Meteo weather adapter — stadium lookup, dome short-circuit, HTTP."""

from datetime import UTC, date, datetime

import httpx
import pytest

from nfl.adapters.outbound.openmeteo_adapter import (
    OpenMeteoAdapter,
    _condition_label,
    _hourly_value,
    _parse_date,
    _Stadium,
)
from nfl.domain.exceptions import NFLNotFoundError, UpstreamAPIError


def _make_adapter(handler, today: date | None = None, stadiums: dict | None = None) -> OpenMeteoAdapter:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, follow_redirects=True)
    fixed_today = today or datetime(2026, 1, 5, tzinfo=UTC).date()
    return OpenMeteoAdapter(client=client, stadiums=stadiums, today=lambda: fixed_today)


_OUTDOOR_PAYLOAD = {
    "hourly": {
        "temperature_2m": [50.0] * 24,
        "wind_speed_10m": [10.0] * 24,
        "precipitation": [0.0] * 24,
        "weather_code": [0] * 16 + [61] + [0] * 7,  # rain at index 16
    }
}


async def test_dome_team_returns_indoor_without_http() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=_OUTDOOR_PAYLOAD)

    adapter = _make_adapter(handler)
    weather = await adapter.get_weather("DET", "20251005")  # DET plays in Ford Field (dome)
    assert weather.is_indoor is True
    assert weather.temperature_f is None
    assert captured == []


async def test_outdoor_past_date_uses_archive_endpoint() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=_OUTDOOR_PAYLOAD)

    adapter = _make_adapter(handler, today=date(2026, 1, 5))
    await adapter.get_weather("KC", "20250915")  # past date → archive
    assert "archive-api" in str(captured[0].url)


async def test_outdoor_future_date_uses_forecast_endpoint() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=_OUTDOOR_PAYLOAD)

    adapter = _make_adapter(handler, today=date(2026, 1, 5))
    await adapter.get_weather("KC", "20260118")  # future date → forecast
    url = str(captured[0].url)
    assert "api.open-meteo.com/v1/forecast" in url
    assert "latitude=39." in url
    assert "longitude=-94." in url


async def test_outdoor_returns_kickoff_hour_values() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_OUTDOOR_PAYLOAD)

    adapter = _make_adapter(handler, today=date(2026, 1, 5))
    weather = await adapter.get_weather("KC", "20250915")
    assert weather.is_indoor is False
    assert weather.temperature_f == 50.0
    assert weather.wind_mph == 10.0
    assert weather.condition == "Rain"  # weather_code 61 at index 16


async def test_unknown_team_raises_not_found() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_OUTDOOR_PAYLOAD)

    adapter = _make_adapter(handler)
    with pytest.raises(NFLNotFoundError):
        await adapter.get_weather("XXX", "20250915")


async def test_open_meteo_500_raises_upstream_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={})

    adapter = _make_adapter(handler)
    with pytest.raises(UpstreamAPIError):
        await adapter.get_weather("KC", "20250915")


async def test_team_abbr_is_case_insensitive() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_OUTDOOR_PAYLOAD)

    adapter = _make_adapter(handler)
    weather = await adapter.get_weather("kc", "20250915")
    assert weather.is_indoor is False


def test_parse_date_rejects_bad_format() -> None:
    with pytest.raises(ValueError):
        _parse_date("2025-09-15")


def test_hourly_value_missing_data_returns_none() -> None:
    assert _hourly_value({}, "temperature_2m", 16) is None
    assert _hourly_value({"hourly": {"temperature_2m": [1, 2]}}, "temperature_2m", 16) is None


def test_condition_label_known_and_unknown() -> None:
    assert _condition_label(0) == "Clear"
    assert _condition_label(61) == "Rain"
    assert _condition_label(999) == "Unknown"
    assert _condition_label(None) is None


def test_custom_stadium_overrides_embedded_map() -> None:
    custom = {"FOO": _Stadium(0.0, 0.0, True)}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    import asyncio

    async def runner():
        adapter = _make_adapter(handler, stadiums=custom)
        weather = await adapter.get_weather("FOO", "20250915")
        assert weather.is_indoor is True

    asyncio.run(runner())
