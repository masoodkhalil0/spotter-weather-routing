"""Pure-Python heatmap builder for route corridor weather risk."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import floor
from typing import Sequence

from trips.services.checkpoints import polyline_length_miles
from trips.services.demo import apply_demo_weather, is_demo_mode_active
from trips.services.risk import WeatherConditions, assess_risk
from trips.services.routing import Route
from trips.services.weather import WeatherServiceError, conditions_at, fetch_forecasts


GRID_CELL_SIZE_DEGREES: float = 0.1
COORDINATE_ROUND_DIGITS: int = 5
WIND_ROUND_DIGITS: int = 1
PRECIPITATION_ROUND_DIGITS: int = 2
LEVEL_NAMES: list[str] = ["LOW", "MODERATE", "HIGH", "SEVERE", "NO_TRAVEL"]


def _validate_departure(departure: datetime) -> None:
    if departure.tzinfo is None or departure.utcoffset() is None:
        raise ValueError("departure must be timezone-aware")


def _validate_load_weight(load_weight_lb: float) -> None:
    if load_weight_lb < 0:
        raise ValueError("load_weight_lb cannot be negative")


def _validate_hours(hours: int) -> None:
    if not 1 <= hours <= 48:
        raise ValueError("hours must be between 1 and 48")


def _validate_max_points(max_points: int) -> None:
    if max_points < 2:
        raise ValueError("max_points must be at least 2")


def _iso_utc(value: datetime) -> str:
    normalized = value.astimezone(timezone.utc).replace(microsecond=0)
    return normalized.isoformat().replace("+00:00", "Z")


def _round_hour_down(value: datetime) -> datetime:
    return value.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)


def _grid_key(point: tuple[float, float]) -> tuple[int, int]:
    lat, lon = point
    return floor(lat / GRID_CELL_SIZE_DEGREES), floor(lon / GRID_CELL_SIZE_DEGREES)


def _point_at_fraction(
    coordinates: Sequence[tuple[float, float]],
    segment_lengths: Sequence[float],
    fraction: float,
    total_length: float,
) -> tuple[float, float]:
    if fraction <= 0.0:
        return coordinates[0]
    if fraction >= 1.0 or total_length == 0.0:
        return coordinates[-1]

    target = total_length * fraction
    traversed = 0.0
    for index, segment_length in enumerate(segment_lengths, start=1):
        next_traversed = traversed + segment_length
        if target <= next_traversed or index == len(coordinates) - 1:
            start_lat, start_lon = coordinates[index - 1]
            end_lat, end_lon = coordinates[index]
            if segment_length == 0.0:
                return coordinates[index]
            segment_fraction = (target - traversed) / segment_length
            return (
                start_lat + (end_lat - start_lat) * segment_fraction,
                start_lon + (end_lon - start_lon) * segment_fraction,
            )
        traversed = next_traversed
    return coordinates[-1]


def _sample_route_points(route: Route, count: int) -> list[tuple[float, float]]:
    if count <= 1:
        return [route.coordinates[0], route.coordinates[-1]]

    coordinates = route.coordinates
    if len(coordinates) == 2:
        total_length = polyline_length_miles(coordinates)
        return [
            _point_at_fraction(coordinates, (total_length,), index / (count - 1), total_length)
            for index in range(count)
        ]

    segment_lengths = [
        polyline_length_miles((coordinates[index - 1], coordinates[index]))
        for index in range(1, len(coordinates))
    ]
    total_length = sum(segment_lengths)
    return [
        _point_at_fraction(coordinates, segment_lengths, index / (count - 1), total_length)
        for index in range(count)
    ]


def _corridor_points(routes: Sequence[Route], max_points: int) -> list[tuple[float, float]]:
    if not routes:
        return []

    per_route = max(2, max_points // len(routes))
    sampled: list[tuple[float, float]] = []
    for route in routes:
        sampled.extend(_sample_route_points(route, per_route))

    unique_points: list[tuple[float, float]] = []
    seen_cells: set[tuple[int, int]] = set()
    for point in sampled:
        key = _grid_key(point)
        if key in seen_cells:
            continue
        seen_cells.add(key)
        unique_points.append(point)
        if len(unique_points) >= max_points:
            break
    return unique_points


def build_heatmap(
    routes: Sequence[Route],
    departure: datetime,
    load_weight_lb: float,
    hours: int = 48,
    max_points: int = 60,
    origin_timezone: str | None = None,
) -> dict[str, object]:
    """Build a compact JSON-serialisable weather-risk heatmap payload."""

    _validate_departure(departure)
    _validate_load_weight(load_weight_lb)
    _validate_hours(hours)
    _validate_max_points(max_points)

    demo_mode_active = is_demo_mode_active()
    points = _corridor_points(routes, max_points=max_points)
    start_time = _round_hour_down(departure)
    end_time = start_time + timedelta(hours=hours)
    forecasts = fetch_forecasts(
        points,
        start=departure.astimezone(timezone.utc).date(),
        end=end_time.astimezone(timezone.utc).date(),
    )

    serialized_points: list[dict[str, object]] = []
    total_distance = max((route.distance_miles for route in routes), default=0.0)
    last_point_index = len(points) - 1
    for point_index, (point, forecast) in enumerate(zip(points, forecasts, strict=True)):
        levels: list[int | None] = []
        wind_values: list[float | None] = []
        rain_values: list[float | None] = []
        snow_values: list[float | None] = []

        for hour_offset in range(hours):
            target_time = start_time + timedelta(hours=hour_offset)
            try:
                conditions = conditions_at(forecast, target_time)
            except WeatherServiceError:
                levels.append(None)
                wind_values.append(None)
                rain_values.append(None)
                snow_values.append(None)
                continue

            if demo_mode_active:
                mile_marker = 0.0 if last_point_index <= 0 else (total_distance * point_index / last_point_index)
                conditions = WeatherConditions(**apply_demo_weather(
                    {
                        "wind_mph": conditions.wind_mph,
                        "rain_in_hr": conditions.rain_in_hr,
                        "snow_in_hr": conditions.snow_in_hr,
                    },
                    mile_marker,
                    hour_offset,
                ))

            assessment = assess_risk(conditions, load_weight_lb)
            levels.append(int(assessment.level))
            wind_values.append(round(conditions.wind_mph, WIND_ROUND_DIGITS))
            rain_values.append(round(conditions.rain_in_hr, PRECIPITATION_ROUND_DIGITS))
            snow_values.append(round(conditions.snow_in_hr, PRECIPITATION_ROUND_DIGITS))

        serialized_points.append(
            {
                "lat": round(point[0], COORDINATE_ROUND_DIGITS),
                "lon": round(point[1], COORDINATE_ROUND_DIGITS),
                "levels": levels,
                "wind": wind_values,
                "rain": rain_values,
                "snow": snow_values,
            }
        )

    result = {
        "departure": _iso_utc(departure),
        "origin_timezone": origin_timezone,
        "hours": hours,
        "start_time": _iso_utc(start_time),
        "load_weight_lb": float(load_weight_lb),
        "level_names": LEVEL_NAMES,
        "points": serialized_points,
    }
    if demo_mode_active:
        result["demo_mode"] = True
    return result