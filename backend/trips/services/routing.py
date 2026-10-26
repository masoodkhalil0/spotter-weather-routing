"""Route retrieval and alternative generation using OSRM."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from math import asin, atan2, cos, degrees, radians, sin, sqrt
from time import sleep
from typing import Any, Iterable, Sequence

import requests
from django.core.cache import cache
from requests import Response
from requests.exceptions import RequestException, Timeout

from trips.services.checkpoints import EARTH_RADIUS_MILES, haversine_miles, polyline_length_miles


OSRM_BASE_URL: str = "https://router.project-osrm.org/route/v1/driving"
METERS_PER_MILE: float = 1609.344
TRUCK_SPEED_FACTOR: float = 0.9
"""OSRM assumes car speeds; trucks average about 90% of that speed."""
CONNECT_TIMEOUT_SECONDS: float = 3.05
READ_TIMEOUT_SECONDS: float = 15.0
CACHE_TTL_SECONDS: int = 3600
MAX_ROUTES: int = 3
MAX_REQUESTS_PER_CALL: int = 5
VIA_MAX_LENGTH_RATIO: float = 1.35
VIA_MAX_SNAP_MILES: float = 10.0
DISTINCT_OVERLAP_LIMIT: float = 0.70
OVERLAP_RADIUS_MILES: float = 2.0
VIA_OFFSET_PRIMARY_RATIO: float = 0.12
VIA_OFFSET_SECONDARY_RATIO: float = 0.20
VIA_OFFSET_MIN_MILES: float = 15.0
VIA_OFFSET_MAX_MILES: float = 60.0
MAX_OVERLAP_POINTS: int = 200
GRID_CELL_SIZE_DEGREES: float = 0.1
USER_AGENT: str = "spotter-weather-routing/1.0"
RETRY_BACKOFF_SECONDS: float = 0.1
ROUNDING_PRECISION: int = 4
LATITUDE_MIN: float = -90.0
LATITUDE_MAX: float = 90.0
LONGITUDE_MIN: float = -180.0
LONGITUDE_MAX: float = 180.0
EARTH_RADIUS_KM: float = 6371.0088


logger = logging.getLogger(__name__)


class RoutingServiceError(Exception):
    """Raised when routing cannot be completed cleanly."""


@dataclass(frozen=True)
class Route:
    """A route alternative returned or generated for a trip."""

    route_id: str
    coordinates: tuple[tuple[float, float], ...]
    distance_miles: float
    duration_seconds: float
    is_generated: bool


def _validate_coordinate(point: tuple[float, float], name: str) -> None:
    """Validate latitude and longitude bounds."""

    lat, lon = point
    if not LATITUDE_MIN <= lat <= LATITUDE_MAX:
        raise ValueError(f"{name} latitude must be between -90 and 90")
    if not LONGITUDE_MIN <= lon <= LONGITUDE_MAX:
        raise ValueError(f"{name} longitude must be between -180 and 180")


def _validate_origin_destination(
    origin: tuple[float, float],
    destination: tuple[float, float],
) -> None:
    """Validate the requested endpoints."""

    _validate_coordinate(origin, "origin")
    _validate_coordinate(destination, "destination")
    if origin == destination:
        raise ValueError("origin and destination must be different")


def _cache_key(
    origin: tuple[float, float],
    destination: tuple[float, float],
    count: int,
) -> str:
    """Build a stable cache key for a route request."""

    rounded_values = (
        round(origin[0], ROUNDING_PRECISION),
        round(origin[1], ROUNDING_PRECISION),
        round(destination[0], ROUNDING_PRECISION),
        round(destination[1], ROUNDING_PRECISION),
        count,
    )
    return "routing:" + ":".join(str(value) for value in rounded_values)


def _lon_lat_string(points: Sequence[tuple[float, float]]) -> str:
    """Convert (lat, lon) points to OSRM's lon,lat path segment."""

    return ";".join(f"{lon},{lat}" for lat, lon in points)


def _meters_to_miles(distance_meters: float) -> float:
    """Convert meters to miles."""

    return distance_meters / METERS_PER_MILE


def offset_point(lat: float, lon: float, bearing_degrees: float, miles: float) -> tuple[float, float]:
    """Offset a point by bearing and distance along a great circle."""

    _validate_coordinate((lat, lon), "point")

    angular_distance = miles / EARTH_RADIUS_MILES
    bearing = radians(bearing_degrees)
    start_lat = radians(lat)
    start_lon = radians(lon)

    end_lat = asin(
        sin(start_lat) * cos(angular_distance)
        + cos(start_lat) * sin(angular_distance) * cos(bearing)
    )
    end_lon = start_lon + atan2(
        sin(bearing) * sin(angular_distance) * cos(start_lat),
        cos(angular_distance) - sin(start_lat) * sin(end_lat),
    )

    normalized_lon = (degrees(end_lon) + 540.0) % 360.0 - 180.0
    return degrees(end_lat), normalized_lon


def point_at_fraction(
    coordinates: Sequence[tuple[float, float]],
    fraction: float,
) -> tuple[float, float]:
    """Return the point at a fractional distance along a polyline."""

    if len(coordinates) < 2:
        raise ValueError("at least two coordinates are required")
    if not 0.0 <= fraction <= 1.0:
        raise ValueError("fraction must be between 0 and 1")

    total_miles = polyline_length_miles(coordinates)
    if total_miles == 0.0:
        return coordinates[0]

    target_miles = total_miles * fraction
    traversed = 0.0

    for index in range(1, len(coordinates)):
        start = coordinates[index - 1]
        end = coordinates[index]
        segment_length = haversine_miles(start, end)
        if traversed + segment_length >= target_miles:
            if segment_length == 0.0:
                return end
            ratio = (target_miles - traversed) / segment_length
            return (
                start[0] + (end[0] - start[0]) * ratio,
                start[1] + (end[1] - start[1]) * ratio,
            )
        traversed += segment_length

    return coordinates[-1]


def _initial_bearing(start: tuple[float, float], end: tuple[float, float]) -> float:
    """Calculate initial bearing from start to end in degrees."""

    start_lat = radians(start[0])
    start_lon = radians(start[1])
    end_lat = radians(end[0])
    end_lon = radians(end[1])
    delta_lon = end_lon - start_lon

    y = sin(delta_lon) * cos(end_lat)
    x = cos(start_lat) * sin(end_lat) - sin(start_lat) * cos(end_lat) * cos(delta_lon)
    return (degrees(atan2(y, x)) + 360.0) % 360.0


def _point_at_miles(
    coordinates: Sequence[tuple[float, float]],
    target_miles: float,
) -> tuple[tuple[float, float], tuple[float, float]]:
    """Return point and local segment direction at a distance along the polyline."""

    traversed = 0.0
    for index in range(1, len(coordinates)):
        start = coordinates[index - 1]
        end = coordinates[index]
        segment_length = haversine_miles(start, end)
        if traversed + segment_length >= target_miles:
            if segment_length == 0.0:
                return end, (start, end)
            ratio = (target_miles - traversed) / segment_length
            point = (
                start[0] + (end[0] - start[0]) * ratio,
                start[1] + (end[1] - start[1]) * ratio,
            )
            return point, (start, end)
        traversed += segment_length
    return coordinates[-1], (coordinates[-2], coordinates[-1])


def _downsample_points(points: Sequence[tuple[float, float]]) -> tuple[tuple[float, float], ...]:
    """Downsample a polyline to at most MAX_OVERLAP_POINTS evenly spaced points."""

    if len(points) <= MAX_OVERLAP_POINTS:
        return tuple(points)
    last_index = len(points) - 1
    sampled: list[tuple[float, float]] = []
    for sample_index in range(MAX_OVERLAP_POINTS):
        index = round(sample_index * last_index / (MAX_OVERLAP_POINTS - 1))
        sampled.append(points[index])
    return tuple(sampled)


def _grid_key(point: tuple[float, float]) -> tuple[int, int]:
    """Return a coarse grid key for a latitude/longitude point."""

    lat, lon = point
    return int(lat // GRID_CELL_SIZE_DEGREES), int(lon // GRID_CELL_SIZE_DEGREES)


def route_overlap(a: Route, b: Route) -> float:
    """Return overlap ratio using downsampling plus a coarse neighbor search.

    Complexity is O(n + m + k), where n and m are downsampled point counts
    capped at 200 and k is the small neighboring-cell comparison work.
    """

    points_a = _downsample_points(a.coordinates)
    points_b = _downsample_points(b.coordinates)
    shorter, longer = (points_a, points_b) if len(points_a) <= len(points_b) else (points_b, points_a)
    if not shorter:
        return 0.0

    grid: dict[tuple[int, int], list[tuple[float, float]]] = {}
    for point in longer:
        key = _grid_key(point)
        grid.setdefault(key, []).append(point)

    overlap_count = 0
    for point in shorter:
        key_lat, key_lon = _grid_key(point)
        matched = False
        for lat_offset in (-1, 0, 1):
            for lon_offset in (-1, 0, 1):
                for candidate in grid.get((key_lat + lat_offset, key_lon + lon_offset), []):
                    if haversine_miles(point, candidate) <= OVERLAP_RADIUS_MILES:
                        overlap_count += 1
                        matched = True
                        break
                if matched:
                    break
            if matched:
                break

    return max(0.0, min(1.0, overlap_count / len(shorter)))


class _RequestBudget:
    """Track outbound request usage for a single get_routes call."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.used = 0

    def consume(self) -> None:
        """Consume one request slot or fail if exhausted."""

        if self.used >= self.limit:
            raise RoutingServiceError("No route found between these locations")
        self.used += 1


def _request_osrm(
    points: Sequence[tuple[float, float]],
    alternatives: bool | int,
    request_budget: _RequestBudget,
) -> dict[str, Any]:
    """Call OSRM with retry-on-timeout/5xx semantics."""

    path = _lon_lat_string(points)
    url = f"{OSRM_BASE_URL}/{path}"
    params = {
        "alternatives": alternatives,
        "overview": "full",
        "geometries": "geojson",
        "steps": "false",
    }
    headers = {"User-Agent": USER_AGENT}
    last_error: RoutingServiceError | None = None

    for attempt in range(2):
        request_budget.consume()
        try:
            response = requests.get(
                url,
                params=params,
                headers=headers,
                timeout=(CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS),
            )
        except Timeout:
            last_error = RoutingServiceError("Routing service timed out")
            if attempt == 0:
                sleep(RETRY_BACKOFF_SECONDS)
                continue
            raise last_error
        except RequestException:
            raise RoutingServiceError("Unable to contact routing service")

        if response.status_code >= 500:
            last_error = RoutingServiceError("Routing service is unavailable")
            if attempt == 0:
                sleep(RETRY_BACKOFF_SECONDS)
                continue
            raise last_error

        return _parse_response_json(response)

    if last_error is not None:
        raise last_error
    raise RoutingServiceError("Unable to contact routing service")


def _parse_response_json(response: Response) -> dict[str, Any]:
    """Parse JSON from OSRM, hiding raw exceptions."""

    try:
        payload = response.json()
    except ValueError as exc:
        raise RoutingServiceError("Routing service returned malformed data") from exc

    if not isinstance(payload, dict):
        raise RoutingServiceError("Routing service returned malformed data")
    return payload


def _route_from_osrm(route_data: dict[str, Any], *, is_generated: bool) -> Route:
    """Convert one OSRM route object into a Route."""

    try:
        distance_meters = float(route_data["distance"])
        duration_seconds = float(route_data["duration"])
        geometry = route_data["geometry"]
        raw_coordinates = geometry["coordinates"]
    except (KeyError, TypeError, ValueError) as exc:
        raise RoutingServiceError("Routing service returned malformed data") from exc

    coordinates: list[tuple[float, float]] = []
    for coordinate in raw_coordinates:
        try:
            lon, lat = coordinate
        except (TypeError, ValueError) as exc:
            raise RoutingServiceError("Routing service returned malformed data") from exc
        _validate_coordinate((lat, lon), "route")
        coordinates.append((lat, lon))

    if len(coordinates) < 2:
        raise RoutingServiceError("Routing service returned malformed data")

    return Route(
        route_id="",
        coordinates=tuple(coordinates),
        distance_miles=_meters_to_miles(distance_meters),
        duration_seconds=duration_seconds / TRUCK_SPEED_FACTOR,
        is_generated=is_generated,
    )


def _parse_routes(payload: dict[str, Any], *, is_generated: bool) -> list[Route]:
    """Parse OSRM route response data."""

    if payload.get("code") != "Ok":
        raise RoutingServiceError("No route found between these locations")

    routes_data = payload.get("routes")
    if not isinstance(routes_data, list):
        raise RoutingServiceError("Routing service returned malformed data")

    routes = [_route_from_osrm(route_data, is_generated=is_generated) for route_data in routes_data]
    if not routes:
        raise RoutingServiceError("No route found between these locations")
    return routes


def _keep_distinct_routes(routes: Iterable[Route]) -> list[Route]:
    """Keep only routes that are distinct from already-kept ones."""

    kept: list[Route] = []
    for route in routes:
        if any(route_overlap(route, existing) >= DISTINCT_OVERLAP_LIMIT for existing in kept):
            continue
        kept.append(route)
    return kept


def _snap_distance_miles(payload: dict[str, Any], waypoint_index: int) -> float:
    """Read the snap distance for a waypoint from the OSRM payload."""

    waypoints = payload.get("waypoints")
    if not isinstance(waypoints, list) or waypoint_index >= len(waypoints):
        raise RoutingServiceError("Routing service returned malformed data")
    waypoint = waypoints[waypoint_index]
    if not isinstance(waypoint, dict) or "distance" not in waypoint:
        raise RoutingServiceError("Routing service returned malformed data")
    try:
        return _meters_to_miles(float(waypoint["distance"]))
    except (TypeError, ValueError) as exc:
        raise RoutingServiceError("Routing service returned malformed data") from exc


def _clamp(value: float, lower: float, upper: float) -> float:
    """Clamp a numeric value to a closed interval."""

    return max(lower, min(upper, value))


def _candidate_waypoints(base_route: Route) -> list[tuple[float, float]]:
    """Generate via-waypoint candidates from the midpoint normal offsets."""

    midpoint_miles = base_route.distance_miles / 2.0
    midpoint, segment = _point_at_miles(base_route.coordinates, midpoint_miles)
    bearing = _initial_bearing(segment[0], segment[1])
    perpendiculars = ((bearing + 90.0) % 360.0, (bearing - 90.0) % 360.0)

    waypoints: list[tuple[float, float]] = []
    for ratio in (VIA_OFFSET_PRIMARY_RATIO, VIA_OFFSET_SECONDARY_RATIO):
        miles = _clamp(base_route.distance_miles * ratio, VIA_OFFSET_MIN_MILES, VIA_OFFSET_MAX_MILES)
        for perpendicular_bearing in perpendiculars:
            waypoints.append(offset_point(midpoint[0], midpoint[1], perpendicular_bearing, miles))
    return waypoints


def get_routes(
    origin: tuple[float, float],
    destination: tuple[float, float],
    count: int = 3,
) -> list[Route]:
    """Fetch distinct route alternatives and generate via routes if needed."""

    _validate_origin_destination(origin, destination)
    if count < 1:
        raise ValueError("count must be at least 1")

    capped_count = min(count, MAX_ROUTES)
    cache_key = _cache_key(origin, destination, capped_count)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    request_budget = _RequestBudget(MAX_REQUESTS_PER_CALL)
    initial_payload = _request_osrm((origin, destination), MAX_ROUTES, request_budget)
    parsed_routes = _parse_routes(initial_payload, is_generated=False)
    distinct_routes = _keep_distinct_routes(parsed_routes)

    if not distinct_routes:
        raise RoutingServiceError("No route found between these locations")

    shortest_route = min(distinct_routes, key=lambda route: route.duration_seconds)

    if len(distinct_routes) < capped_count:
        for waypoint in _candidate_waypoints(shortest_route):
            if len(distinct_routes) >= capped_count or request_budget.used >= MAX_REQUESTS_PER_CALL:
                break

            try:
                payload = _request_osrm((origin, waypoint, destination), False, request_budget)
                candidate_routes = _parse_routes(payload, is_generated=True)
                if not candidate_routes:
                    logger.warning("Optional generated via route was unusable")
                    continue
                candidate = candidate_routes[0]
            except RoutingServiceError as exc:
                logger.warning("Optional generated via route failed: %s", exc)
                continue

            if _snap_distance_miles(payload, 1) > VIA_MAX_SNAP_MILES:
                continue
            if candidate.distance_miles > shortest_route.distance_miles * VIA_MAX_LENGTH_RATIO:
                continue
            if any(route_overlap(candidate, kept) >= DISTINCT_OVERLAP_LIMIT for kept in distinct_routes):
                continue

            distinct_routes.append(candidate)

    distinct_routes.sort(key=lambda route: route.duration_seconds)
    final_routes = [
        Route(
            route_id=f"route-{index}",
            coordinates=route.coordinates,
            distance_miles=route.distance_miles,
            duration_seconds=route.duration_seconds,
            is_generated=route.is_generated,
        )
        for index, route in enumerate(distinct_routes[:capped_count], start=1)
    ]

    if not final_routes:
        raise RoutingServiceError("No route found between these locations")

    cache.set(cache_key, final_routes, CACHE_TTL_SECONDS)
    return final_routes