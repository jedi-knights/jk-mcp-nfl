"""Outbound adapter — fetches weather conditions from the Open-Meteo public API.

Open-Meteo (https://open-meteo.com) is free and requires no API key. We hit:
- Forecast endpoint  for future/today game dates
- Archive endpoint   for past game dates

Stadium coordinates are embedded as a static map; dome stadiums short-circuit
the HTTP call and return Weather(is_indoor=True). Sample hour for kickoff is
local 16:00 (4pm) — close enough to Sunday afternoon kickoff windows for the
betting use case without needing the exact game time.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

import httpx

from ...domain.exceptions import NFLNotFoundError, UpstreamAPIError
from ...domain.models import Weather

logger = logging.getLogger(__name__)

_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
_KICKOFF_HOUR = 16  # 4pm local — proxy for Sunday afternoon windows
_DEFAULT_TIMEOUT = 30.0


@dataclass(frozen=True)
class _Stadium:
    """Static metadata for an NFL home stadium."""

    lat: float
    lon: float
    is_dome: bool


# 32 teams; LAR/LAC share SoFi (LA), NYG/NYJ share MetLife (East Rutherford).
_STADIUMS: dict[str, _Stadium] = {
    "ARI": _Stadium(33.5276, -112.2626, True),
    "ATL": _Stadium(33.7553, -84.4006, True),
    "BAL": _Stadium(39.2780, -76.6227, False),
    "BUF": _Stadium(42.7738, -78.7868, False),
    "CAR": _Stadium(35.2258, -80.8528, False),
    "CHI": _Stadium(41.8623, -87.6167, False),
    "CIN": _Stadium(39.0954, -84.5160, False),
    "CLE": _Stadium(41.5061, -81.6995, False),
    "DAL": _Stadium(32.7473, -97.0945, True),
    "DEN": _Stadium(39.7439, -105.0201, False),
    "DET": _Stadium(42.3400, -83.0456, True),
    "GB": _Stadium(44.5013, -88.0622, False),
    "HOU": _Stadium(29.6847, -95.4107, True),
    "IND": _Stadium(39.7601, -86.1639, True),
    "JAX": _Stadium(30.3239, -81.6373, False),
    "KC": _Stadium(39.0489, -94.4839, False),
    "LAC": _Stadium(33.9534, -118.3392, True),
    "LAR": _Stadium(33.9534, -118.3392, True),
    "LV": _Stadium(36.0908, -115.1830, True),
    "MIA": _Stadium(25.9580, -80.2389, False),
    "MIN": _Stadium(44.9737, -93.2581, True),
    "NE": _Stadium(42.0909, -71.2643, False),
    "NO": _Stadium(29.9511, -90.0812, True),
    "NYG": _Stadium(40.8128, -74.0742, False),
    "NYJ": _Stadium(40.8128, -74.0742, False),
    "PHI": _Stadium(39.9008, -75.1675, False),
    "PIT": _Stadium(40.4468, -80.0158, False),
    "SEA": _Stadium(47.5952, -122.3316, False),
    "SF": _Stadium(37.4030, -121.9700, False),
    "TB": _Stadium(27.9759, -82.5033, False),
    "TEN": _Stadium(36.1665, -86.7713, False),
    "WAS": _Stadium(38.9078, -76.8645, False),
}


def _utc_today() -> date:
    """Today in UTC, isolated for test injection."""
    return datetime.now(UTC).date()


def _parse_date(date_yyyymmdd: str) -> date:
    """Parse a YYYYMMDD string into a date (raises ValueError on bad input)."""
    return datetime.strptime(date_yyyymmdd, "%Y%m%d").date()


def _check_response(response: httpx.Response, url: str) -> None:
    """Translate non-2xx HTTP responses into domain exceptions."""
    if response.status_code >= 400:
        raise UpstreamAPIError(f"Open-Meteo error {response.status_code}: {url}")


class OpenMeteoAdapter:
    """Looks up stadium coordinates and fetches weather from Open-Meteo."""

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        stadiums: dict[str, _Stadium] | None = None,
        today: Callable[[], date] = _utc_today,
    ) -> None:
        """Initialize the adapter.

        Args:
            client: Optional httpx.AsyncClient. Inject a MockTransport in tests.
            stadiums: Override the embedded stadium map (rarely needed).
            today: Wall-clock helper returning today's date. Injectable for testing.
        """
        self._client = client or httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT, follow_redirects=True)
        self._stadiums = stadiums or _STADIUMS
        self._today = today

    async def get_weather(self, home_team_abbr: str, date_yyyymmdd: str) -> Weather:
        """Return kickoff-hour weather at the home team's stadium.

        Args:
            home_team_abbr: NFL team abbreviation (e.g. "KC").
            date_yyyymmdd: Game date in YYYYMMDD format.

        Raises:
            NFLNotFoundError: If the team abbreviation isn't in the stadium map.
            ValueError: If the date string is malformed.
            UpstreamAPIError: If Open-Meteo returns a non-2xx response.
        """
        stadium = self._stadiums.get(home_team_abbr.upper())
        if stadium is None:
            raise NFLNotFoundError(f"No stadium known for team {home_team_abbr!r}")
        game_id = f"{home_team_abbr.upper()}-{date_yyyymmdd}"
        if stadium.is_dome:
            return Weather(game_id=game_id, is_indoor=True)
        target_date = _parse_date(date_yyyymmdd)
        url = _ARCHIVE_URL if target_date < self._today() else _FORECAST_URL
        params = _query_params(stadium, target_date)
        logger.debug("Open-Meteo GET %s params=%s", url, params)
        response = await self._client.get(url, params=params)
        _check_response(response, url)
        return _parse_open_meteo(game_id, response.json())


def _query_params(stadium: _Stadium, target: date) -> dict[str, Any]:
    """Build the shared query string for Open-Meteo forecast/archive endpoints."""
    iso_date = target.isoformat()
    return {
        "latitude": stadium.lat,
        "longitude": stadium.lon,
        "start_date": iso_date,
        "end_date": iso_date,
        "hourly": "temperature_2m,precipitation,wind_speed_10m,weather_code",
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "timezone": "auto",
    }


def _hourly_value(payload: dict[str, Any], key: str, hour: int) -> float | None:
    """Pull the hour-`hour` value out of an Open-Meteo `hourly` array."""
    hourly = payload.get("hourly")
    if not isinstance(hourly, dict):
        return None
    series = hourly.get(key)
    if not isinstance(series, list) or hour >= len(series):
        return None
    value = series[hour]
    return float(value) if isinstance(value, int | float) else None


# WMO weather codes condensed into human-readable buckets.
# https://open-meteo.com/en/docs/historical-weather-api#weathervariables
_WEATHER_CODES = {
    0: "Clear",
    1: "Mostly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Fog",
    51: "Drizzle",
    53: "Drizzle",
    55: "Drizzle",
    61: "Rain",
    63: "Rain",
    65: "Rain",
    66: "Freezing rain",
    67: "Freezing rain",
    71: "Snow",
    73: "Snow",
    75: "Snow",
    77: "Snow",
    80: "Showers",
    81: "Showers",
    82: "Showers",
    85: "Snow showers",
    86: "Snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm",
    99: "Thunderstorm",
}


def _condition_label(code: float | None) -> str | None:
    """Map a WMO weather code to a human-readable label."""
    if code is None:
        return None
    return _WEATHER_CODES.get(int(code), "Unknown")


def _parse_open_meteo(game_id: str, payload: dict[str, Any]) -> Weather:
    """Map an Open-Meteo response to a Weather domain object at the kickoff hour."""
    return Weather(
        game_id=game_id,
        is_indoor=False,
        temperature_f=_hourly_value(payload, "temperature_2m", _KICKOFF_HOUR),
        wind_mph=_hourly_value(payload, "wind_speed_10m", _KICKOFF_HOUR),
        precipitation_chance=_hourly_value(payload, "precipitation", _KICKOFF_HOUR),
        condition=_condition_label(_hourly_value(payload, "weather_code", _KICKOFF_HOUR)),
    )
