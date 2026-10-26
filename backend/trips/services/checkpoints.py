"""Pure-Python checkpoint sampling and ETA calculation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from math import asin, cos, radians, sin, sqrt
from typing import Sequence


EARTH_RADIUS_MILES: float = 3958.8
LATITUDE_MIN: float = -90.0
LATITUDE_MAX: float = 90.0
LONGITUDE_MIN: float = -180.0
LONGITUDE_MAX: float = 180.0
ROUTE_SHORT_INTERVAL_MILES: int = 10
ROUTE_MEDIUM_INTERVAL_MILES: int = 25
ROUTE_LONG_INTERVAL_MILES: int = 50
ROUTE_SHORT_MAX_MILES: float = 150.0
ROUTE_MEDIUM_MAX_MILES: float = 500.0
SEGMENT_SUM_TOLERANCE: float = 1e-6


@dataclass(frozen=True)
class Checkpoint:
    """A sampled route checkpoint with ETA and represented mileage."""

    index: int
    mile_marker: float
    lat: float
    lon: float
    eta: datetime
    segment_miles: float


def _validate_coordinate(lat: float, lon: float) -> None:
    """Validate latitude and longitude bounds."""

    if not LATITUDE_MIN <= lat <= LATITUDE_MAX:
        raise ValueError("latitude must be between -90 and 90")
    if not LONGITUDE_MIN <= lon <= LONGITUDE_MAX:
        raise ValueError("longitude must be between -180 and 180")


def _validate_coordinates(coordinates: Sequence[tuple[float, float]]) -> None:
    """Validate a polyline coordinate sequence."""

    if len(coordinates) < 2:
        raise ValueError("at least two coordinates are required")
    for lat, lon in coordinates:
        _validate_coordinate(lat, lon)


def _validate_departure(departure: datetime) -> None:
    """Validate that departure is timezone-aware."""

    if departure.tzinfo is None or departure.utcoffset() is None:
        raise ValueError("departure must be timezone-aware")


def haversine_miles(start: tuple[float, float], end: tuple[float, float]) -> float:
    """Return the great-circle distance between two latitude/longitude points."""

    start_lat, start_lon = start
    end_lat, end_lon = end
    _validate_coordinate(start_lat, start_lon)
    _validate_coordinate(end_lat, end_lon)

    lat1 = radians(start_lat)
    lon1 = radians(start_lon)
    lat2 = radians(end_lat)
    lon2 = radians(end_lon)

    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1

    a = (
        sin(delta_lat / 2.0) ** 2
        + cos(lat1) * cos(lat2) * sin(delta_lon / 2.0) ** 2
    )
    c = 2.0 * asin(min(1.0, sqrt(a)))
    return EARTH_RADIUS_MILES * c


def choose_interval_miles(total_miles: float) -> int:
    """Choose a checkpoint interval based on route length."""

    if total_miles <= ROUTE_SHORT_MAX_MILES:
        return ROUTE_SHORT_INTERVAL_MILES
    if total_miles <= ROUTE_MEDIUM_MAX_MILES:
        return ROUTE_MEDIUM_INTERVAL_MILES
    return ROUTE_LONG_INTERVAL_MILES


def polyline_length_miles(coordinates: Sequence[tuple[float, float]]) -> float:
    """Return the total length of a polyline in miles."""

    _validate_coordinates(coordinates)

    total = 0.0
    for index in range(1, len(coordinates)):
        total += haversine_miles(coordinates[index - 1], coordinates[index])
    return total


def _interpolate_point(
    start: tuple[float, float],
    end: tuple[float, float],
    fraction: float,
) -> tuple[float, float]:
    """Linearly interpolate between two polyline vertices."""

    start_lat, start_lon = start
    end_lat, end_lon = end
    lat = start_lat + (end_lat - start_lat) * fraction
    lon = start_lon + (end_lon - start_lon) * fraction
    return lat, lon


def _mile_markers(total_miles: float, interval_miles: float) -> list[float]:
    """Build all checkpoint mile markers including the final point."""

    if total_miles == 0.0:
        return [0.0]

    markers: list[float] = [0.0]
    next_marker = interval_miles

    while next_marker < total_miles:
        markers.append(next_marker)
        next_marker += interval_miles

    if markers[-1] != total_miles:
        markers.append(total_miles)
    return markers


def _checkpoint_positions(
    coordinates: Sequence[tuple[float, float]],
    markers: Sequence[float],
) -> list[tuple[float, float]]:
    """Map mile markers onto interpolated polyline positions."""

    if len(markers) == 1:
        return [coordinates[0]]

    positions: list[tuple[float, float]] = []
    segment_index = 1
    traversed = 0.0
    segment_length = haversine_miles(coordinates[0], coordinates[1])

    for marker in markers:
        while (
            segment_index < len(coordinates) - 1
            and marker > traversed + segment_length
        ):
            traversed += segment_length
            segment_index += 1
            segment_length = haversine_miles(
                coordinates[segment_index - 1],
                coordinates[segment_index],
            )

        if segment_length == 0.0:
            positions.append(coordinates[segment_index])
            continue

        distance_into_segment = marker - traversed
        fraction = distance_into_segment / segment_length
        positions.append(
            _interpolate_point(
                coordinates[segment_index - 1],
                coordinates[segment_index],
                fraction,
            )
        )

    return positions


def _segment_miles(markers: Sequence[float]) -> list[float]:
    """Compute represented mileage for each checkpoint."""

    if len(markers) == 1:
        return [0.0]

    segments: list[float] = []
    for index, marker in enumerate(markers):
        previous_gap = 0.0 if index == 0 else marker - markers[index - 1]
        next_gap = 0.0 if index == len(markers) - 1 else markers[index + 1] - marker
        segment = 0.0
        if index > 0:
            segment += previous_gap / 2.0
        if index < len(markers) - 1:
            segment += next_gap / 2.0
        segments.append(segment)
    return segments


def generate_checkpoints(
    coordinates: Sequence[tuple[float, float]],
    duration_seconds: float,
    departure: datetime,
    interval_miles: float,
) -> list[Checkpoint]:
    """Generate interpolated checkpoints with ETAs across a route."""

    _validate_coordinates(coordinates)
    _validate_departure(departure)

    if interval_miles <= 0:
        raise ValueError("interval_miles must be greater than 0")
    if duration_seconds < 0:
        raise ValueError("duration_seconds cannot be negative")

    total_miles = polyline_length_miles(coordinates)
    if total_miles == 0.0:
        lat, lon = coordinates[0]
        return [
            Checkpoint(
                index=0,
                mile_marker=0.0,
                lat=lat,
                lon=lon,
                eta=departure,
                segment_miles=0.0,
            )
        ]

    markers = _mile_markers(total_miles, interval_miles)
    positions = _checkpoint_positions(coordinates, markers)
    represented_segments = _segment_miles(markers)

    checkpoints: list[Checkpoint] = []
    for index, (marker, position, segment_miles) in enumerate(
        zip(markers, positions, represented_segments, strict=True)
    ):
        eta_offset_seconds = duration_seconds * (marker / total_miles)
        checkpoints.append(
            Checkpoint(
                index=index,
                mile_marker=marker,
                lat=position[0],
                lon=position[1],
                eta=departure + timedelta(seconds=eta_offset_seconds),
                segment_miles=segment_miles,
            )
        )

    total_segments = sum(checkpoint.segment_miles for checkpoint in checkpoints)
    if abs(total_segments - total_miles) > SEGMENT_SUM_TOLERANCE:
        raise ValueError("segment miles must sum to total miles")

    return checkpoints