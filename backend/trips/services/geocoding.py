"""Geocoding helpers backed by Nominatim search."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import logging
import re
import time

from django.conf import settings
from django.core.cache import cache
import requests
from requests import Response
from requests.exceptions import RequestException, Timeout


NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
MIN_QUERY_LENGTH = 3
MAX_QUERY_LENGTH = 200
MIN_LIMIT = 1
MAX_LIMIT = 10
REQUEST_TIMEOUT = (3.05, 10)
CACHE_TTL_SECONDS = 24 * 60 * 60
RATE_LOCK_TTL_SECONDS = 1
RATE_GUARD_MAX_WAIT_SECONDS = 1.1
RATE_GUARD_SLEEP_SECONDS = 0.2
RETRY_BACKOFF_SECONDS = 0.25
LATITUDE_MIN = -90.0
LATITUDE_MAX = 90.0
LONGITUDE_MIN = -180.0
LONGITUDE_MAX = 180.0
COUNTRY_CODES_PATTERN = re.compile(r"^[a-z,]+$")


logger = logging.getLogger("trips")


@dataclass(frozen=True)
class Place:
    """A geocoded place match."""

    label: str
    lat: float
    lon: float


class GeocodingError(Exception):
    """Raised when the geocoding service cannot provide a valid response."""


def _normalize_query(query: str) -> str:
    """Trim and collapse repeated whitespace in a search query."""

    normalized = " ".join(query.split())
    if not MIN_QUERY_LENGTH <= len(normalized) <= MAX_QUERY_LENGTH:
        raise ValueError(
            f"query must be between {MIN_QUERY_LENGTH} and {MAX_QUERY_LENGTH} characters"
        )
    return normalized


def _cache_key(query: str, limit: int) -> str:
    """Build a cache key for a normalized query and limit."""

    digest = hashlib.sha256(f"{query.lower()}:{limit}".encode("utf-8")).hexdigest()
    return f"geocoding:{digest}"


def _rate_guard_key() -> str:
    """Return the cache key used to coordinate a simple 1 rps guard."""

    return "geocoding:nominatim:rate-lock"


def _wait_for_rate_guard() -> None:
    """Use a short cache lock plus brief sleeps to stay near Nominatim's 1 rps limit."""

    deadline = time.monotonic() + RATE_GUARD_MAX_WAIT_SECONDS
    # cache.add() succeeds only when the key is absent, so it acts as a tiny cross-process lock.
    while not cache.add(_rate_guard_key(), "1", timeout=RATE_LOCK_TTL_SECONDS):
        if time.monotonic() >= deadline:
            break
        time.sleep(RATE_GUARD_SLEEP_SECONDS)


def _country_codes_param() -> str | None:
    """Return validated Nominatim country codes from settings, if configured."""

    value = settings.GEOCODE_COUNTRY_CODES.strip()
    if not value:
        return None

    if not COUNTRY_CODES_PATTERN.fullmatch(value) or ",," in value:
        logger.warning("Ignoring invalid GEOCODE_COUNTRY_CODES setting: %s", value)
        return None

    return value


def _request_places(query: str, limit: int) -> Response:
    """Call the Nominatim endpoint with one retry for timeouts and 5xx responses."""

    headers = {"User-Agent": settings.OUTBOUND_USER_AGENT}
    params = {
        "q": query,
        "format": "jsonv2",
        "limit": limit,
        "accept-language": "en",
    }
    country_codes = _country_codes_param()
    if country_codes is not None:
        params["countrycodes"] = country_codes

    _wait_for_rate_guard()

    for attempt in range(2):
        try:
            response = requests.get(
                NOMINATIM_SEARCH_URL,
                params=params,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            )
        except Timeout as exc:
            if attempt == 0:
                time.sleep(RETRY_BACKOFF_SECONDS)
                continue
            raise GeocodingError("Geocoding service timed out") from exc
        except RequestException as exc:
            raise GeocodingError("Geocoding service request failed") from exc

        if response.status_code >= 500:
            if attempt == 0:
                time.sleep(RETRY_BACKOFF_SECONDS)
                continue
            raise GeocodingError("Geocoding service is unavailable")

        if response.status_code >= 400:
            raise GeocodingError("Geocoding service returned an invalid response")

        return response

    raise GeocodingError("Geocoding service is unavailable")


def _parse_places(payload: object) -> list[Place]:
    """Validate the response payload and convert valid items to Place values."""

    if not isinstance(payload, list):
        raise GeocodingError("Geocoding service returned malformed data")

    places: list[Place] = []
    for item in payload:
        if not isinstance(item, dict):
            continue

        label = item.get("display_name")
        lat_value = item.get("lat")
        lon_value = item.get("lon")
        if not isinstance(label, str):
            continue

        try:
            lat = float(lat_value)
            lon = float(lon_value)
        except (TypeError, ValueError):
            continue

        if not LATITUDE_MIN <= lat <= LATITUDE_MAX:
            continue
        if not LONGITUDE_MIN <= lon <= LONGITUDE_MAX:
            continue

        places.append(Place(label=label, lat=lat, lon=lon))

    return places


def search_places(query: str, limit: int = 5) -> list[Place]:
    """Search for places using the Nominatim API with caching and retry logic."""

    normalized_query = _normalize_query(query)
    if not MIN_LIMIT <= limit <= MAX_LIMIT:
        raise ValueError(f"limit must be between {MIN_LIMIT} and {MAX_LIMIT}")

    cache_key = _cache_key(normalized_query, limit)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    response = _request_places(normalized_query, limit)
    try:
        payload = response.json()
    except (ValueError, json.JSONDecodeError) as exc:
        raise GeocodingError("Geocoding service returned malformed data") from exc

    places = _parse_places(payload)
    cache.set(cache_key, places, timeout=CACHE_TTL_SECONDS)
    return places