"""Forecast fetching and hourly weather selection via Open-Meteo."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from time import sleep
from typing import Any, Sequence

import requests
from django.core.cache import cache
from requests import Response
from requests.exceptions import RequestException, Timeout

from trips.services.risk import WeatherConditions


FORECAST_URL: str = "https://api.open-meteo.com/v1/forecast"
HOURLY_VARIABLES: str = "wind_speed_10m,rain,showers,snowfall"
WIND_SPEED_UNIT: str = "mph"
PRECIPITATION_UNIT: str = "inch"
FORECAST_TIMEZONE: str = "UTC"
BATCH_SIZE: int = 50
CONNECT_TIMEOUT_SECONDS: float = 3.05
READ_TIMEOUT_SECONDS: float = 10.0
CACHE_TTL_SECONDS: int = 900
RETRY_BACKOFF_SECONDS: float = 0.1
ROUNDING_PRECISION: int = 2
USER_AGENT: str = "spotter-weather-routing/1.0"
FORECAST_MARGIN_MINUTES: int = 90


class WeatherServiceError(Exception):
    """Raised when forecast retrieval or lookup fails cleanly."""


@dataclass(frozen=True)
class HourlyForecast:
    """Normalized hourly forecast values for one location."""

    times: tuple[datetime, ...]
    wind_mph: tuple[float, ...]
    rain_in: tuple[float, ...]
    snow_in: tuple[float, ...]


def _rounded_point(point: tuple[float, float]) -> tuple[float, float]:
    """Round a point for cache keys and API requests."""

    return round(point[0], ROUNDING_PRECISION), round(point[1], ROUNDING_PRECISION)


def _cache_key(point: tuple[float, float], start: date, end: date) -> str:
    """Build the per-point forecast cache key."""

    lat, lon = point
    return f"weather:{lat}:{lon}:{start.isoformat()}:{end.isoformat()}"


def _parse_timestamp(value: str) -> datetime:
    """Parse an Open-Meteo UTC timestamp."""

    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise WeatherServiceError("Weather service returned malformed data") from exc

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _normalize_numeric(value: Any) -> float:
    """Convert API numeric values, treating None as 0.0."""

    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise WeatherServiceError("Weather service returned malformed data") from exc


def _normalize_payload_list(payload: Any, expected_length: int) -> list[dict[str, Any]]:
    """Normalize single-object and multi-object API payloads to a list."""

    if isinstance(payload, dict):
        items = [payload]
    elif isinstance(payload, list):
        items = payload
    else:
        raise WeatherServiceError("Weather service returned malformed data")

    if len(items) != expected_length:
        raise WeatherServiceError("Weather service returned malformed data")
    if not all(isinstance(item, dict) for item in items):
        raise WeatherServiceError("Weather service returned malformed data")
    return items


def _forecast_from_item(item: dict[str, Any]) -> HourlyForecast:
    """Validate and convert one Open-Meteo forecast object."""

    hourly = item.get("hourly")
    if not isinstance(hourly, dict):
        raise WeatherServiceError("Weather service returned malformed data")

    required_keys = ("time", "wind_speed_10m", "rain", "showers", "snowfall")
    if any(key not in hourly for key in required_keys):
        raise WeatherServiceError("Weather service returned malformed data")

    times_raw = hourly["time"]
    wind_raw = hourly["wind_speed_10m"]
    rain_raw = hourly["rain"]
    showers_raw = hourly["showers"]
    snow_raw = hourly["snowfall"]

    if not all(isinstance(values, list) for values in (times_raw, wind_raw, rain_raw, showers_raw, snow_raw)):
        raise WeatherServiceError("Weather service returned malformed data")

    length = len(times_raw)
    if any(len(values) != length for values in (wind_raw, rain_raw, showers_raw, snow_raw)):
        raise WeatherServiceError("Weather service returned malformed data")

    times = tuple(_parse_timestamp(value) for value in times_raw)
    wind_mph = tuple(_normalize_numeric(value) for value in wind_raw)
    rain_in = tuple(
        _normalize_numeric(rain_value) + _normalize_numeric(showers_value)
        for rain_value, showers_value in zip(rain_raw, showers_raw, strict=True)
    )
    snow_in = tuple(_normalize_numeric(value) for value in snow_raw)

    return HourlyForecast(
        times=times,
        wind_mph=wind_mph,
        rain_in=rain_in,
        snow_in=snow_in,
    )


def _parse_response_json(response: Response) -> Any:
    """Parse response JSON without leaking low-level exceptions."""

    try:
        return response.json()
    except ValueError as exc:
        raise WeatherServiceError("Weather service returned malformed data") from exc


def _request_batch(points: Sequence[tuple[float, float]], start: date, end: date) -> list[HourlyForecast]:
    """Request one batch of forecasts with retry-on-timeout/5xx."""

    params = {
        "latitude": ",".join(str(point[0]) for point in points),
        "longitude": ",".join(str(point[1]) for point in points),
        "hourly": HOURLY_VARIABLES,
        "wind_speed_unit": WIND_SPEED_UNIT,
        "precipitation_unit": PRECIPITATION_UNIT,
        "timezone": FORECAST_TIMEZONE,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
    }
    headers = {"User-Agent": USER_AGENT}
    last_error: WeatherServiceError | None = None

    for attempt in range(2):
        try:
            response = requests.get(
                FORECAST_URL,
                params=params,
                headers=headers,
                timeout=(CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS),
            )
        except Timeout:
            last_error = WeatherServiceError("Weather service timed out")
            if attempt == 0:
                sleep(RETRY_BACKOFF_SECONDS)
                continue
            raise last_error
        except RequestException:
            raise WeatherServiceError("Unable to contact weather service")

        if response.status_code >= 500:
            last_error = WeatherServiceError("Weather service is unavailable")
            if attempt == 0:
                sleep(RETRY_BACKOFF_SECONDS)
                continue
            raise last_error

        payload = _parse_response_json(response)
        items = _normalize_payload_list(payload, len(points))
        return [_forecast_from_item(item) for item in items]

    if last_error is not None:
        raise last_error
    raise WeatherServiceError("Unable to contact weather service")


def fetch_forecasts(
    points: Sequence[tuple[float, float]],
    start: date,
    end: date,
) -> list[HourlyForecast]:
    """Fetch hourly forecasts for points, using batching and cache."""

    if end < start:
        raise ValueError("end date must not be before start date")

    rounded_points = [_rounded_point(point) for point in points]

    point_to_indices: dict[tuple[float, float], list[int]] = {}
    ordered_unique_points: list[tuple[float, float]] = []
    for index, point in enumerate(rounded_points):
        if point not in point_to_indices:
            point_to_indices[point] = []
            ordered_unique_points.append(point)
        point_to_indices[point].append(index)

    results: list[HourlyForecast | None] = [None] * len(points)
    missing_points: list[tuple[float, float]] = []

    for point in ordered_unique_points:
        cached_forecast = cache.get(_cache_key(point, start, end))
        if cached_forecast is None:
            missing_points.append(point)
            continue
        for index in point_to_indices[point]:
            results[index] = cached_forecast

    for batch_start in range(0, len(missing_points), BATCH_SIZE):
        batch = missing_points[batch_start : batch_start + BATCH_SIZE]
        forecasts = _request_batch(batch, start, end)
        for point, forecast in zip(batch, forecasts, strict=True):
            cache.set(_cache_key(point, start, end), forecast, CACHE_TTL_SECONDS)
            for index in point_to_indices[point]:
                results[index] = forecast

    if any(result is None for result in results):
        raise WeatherServiceError("Weather service returned malformed data")

    return [result for result in results if result is not None]


def conditions_at(forecast: HourlyForecast, when: datetime) -> WeatherConditions:
    """Return forecast conditions nearest to the requested aware datetime."""

    if when.tzinfo is None or when.utcoffset() is None:
        raise ValueError("when must be timezone-aware")
    if not forecast.times:
        raise WeatherServiceError("forecast does not cover this time")

    when_utc = when.astimezone(timezone.utc)
    first_time = forecast.times[0]
    last_time = forecast.times[-1]
    margin = timedelta(minutes=FORECAST_MARGIN_MINUTES)

    if when_utc < first_time - margin or when_utc > last_time + margin:
        raise WeatherServiceError("forecast does not cover this time")

    nearest_index = min(
        range(len(forecast.times)),
        key=lambda index: abs(forecast.times[index] - when_utc),
    )

    return WeatherConditions(
        wind_mph=forecast.wind_mph[nearest_index],
        rain_in_hr=forecast.rain_in[nearest_index],
        snow_in_hr=forecast.snow_in[nearest_index],
    )