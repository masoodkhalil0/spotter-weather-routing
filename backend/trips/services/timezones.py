"""Timezone lookup and departure resolution helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests
from django.core.cache import cache
from django.utils import timezone as django_timezone
from requests.exceptions import RequestException, Timeout

from trips.services.weather import (
    CONNECT_TIMEOUT_SECONDS,
    FORECAST_URL,
    READ_TIMEOUT_SECONDS,
    USER_AGENT,
)


TIMEZONE_CACHE_TTL_SECONDS: int = 86400
ROUNDING_PRECISION: int = 2
TIMEZONE_UPSTREAM_DETAIL: str = "Timezone upstream failed."


class TimezoneLookupError(Exception):
    """Raised when origin timezone lookup or validation fails."""


def _rounded_coordinates(lat: float, lon: float) -> tuple[float, float]:
    """Round coordinates for cache keys and upstream requests."""

    return round(lat, ROUNDING_PRECISION), round(lon, ROUNDING_PRECISION)


def _cache_key(lat: float, lon: float) -> str:
    """Build the timezone cache key."""

    rounded_lat, rounded_lon = _rounded_coordinates(lat, lon)
    return f"timezone:{rounded_lat}:{rounded_lon}"


def _utc_offset_minutes(tz_name: str) -> int:
    """Compute the current UTC offset in minutes using the IANA zone."""

    try:
        tzinfo = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError as exc:
        raise TimezoneLookupError(TIMEZONE_UPSTREAM_DETAIL) from exc

    offset = django_timezone.now().astimezone(tzinfo).utcoffset()
    if offset is None:
        raise TimezoneLookupError(TIMEZONE_UPSTREAM_DETAIL)
    return int(offset.total_seconds() // 60)


def lookup_timezone(lat: float, lon: float) -> dict[str, object]:
    """Look up the origin timezone through Open-Meteo and cache the result."""

    cache_key = _cache_key(lat, lon)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    rounded_lat, rounded_lon = _rounded_coordinates(lat, lon)
    try:
        response = requests.get(
            FORECAST_URL,
            params={
                "latitude": rounded_lat,
                "longitude": rounded_lon,
                "timezone": "auto",
                "forecast_days": 1,
                "hourly": "temperature_2m",
            },
            headers={"User-Agent": USER_AGENT},
            timeout=(CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS),
        )
    except (Timeout, RequestException) as exc:
        raise TimezoneLookupError(TIMEZONE_UPSTREAM_DETAIL) from exc

    if response.status_code >= 400:
        raise TimezoneLookupError(TIMEZONE_UPSTREAM_DETAIL)

    try:
        payload = response.json()
    except ValueError as exc:
        raise TimezoneLookupError(TIMEZONE_UPSTREAM_DETAIL) from exc

    tz_name = payload.get("timezone")
    if not isinstance(tz_name, str) or not tz_name:
        raise TimezoneLookupError(TIMEZONE_UPSTREAM_DETAIL)

    result = {
        "timezone": tz_name,
        "utc_offset_minutes": _utc_offset_minutes(tz_name),
    }
    cache.set(cache_key, result, TIMEZONE_CACHE_TTL_SECONDS)
    return result


def resolve_departure(departure: datetime, tz_name: str) -> datetime:
    """Return the departure instant as an aware UTC datetime."""

    if departure.tzinfo is not None and departure.utcoffset() is not None:
        return departure.astimezone(timezone.utc)

    try:
        tzinfo = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError as exc:
        raise TimezoneLookupError(TIMEZONE_UPSTREAM_DETAIL) from exc

    # DST gaps/overlaps are accepted with zoneinfo's default fold=0 behaviour.
    localized = departure.replace(tzinfo=tzinfo)
    return localized.astimezone(timezone.utc)