"""Trip analysis pipeline combining routing, weather, checkpoints, and risk."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Sequence

from trips.services.checkpoints import Checkpoint, choose_interval_miles, generate_checkpoints
from trips.services.demo import apply_demo_weather, is_demo_mode_active
from trips.services.recommend import explain_recommendation, rank_routes, summarize_route
from trips.services.risk import RiskAssessment, RiskLevel, WeatherConditions, assess_risk
from trips.services.routing import Route, get_routes
from trips.services.weather import HourlyForecast, conditions_at, fetch_forecasts


MAX_GEOMETRY_POINTS: int = 500
MILES_ROUND_DIGITS: int = 1
AVERAGE_RISK_ROUND_DIGITS: int = 2
COORDINATE_ROUND_DIGITS: int = 5
WEATHER_ROUND_DIGITS: int = 2


def downsample_geometry(
    coordinates: Sequence[tuple[float, float]],
    max_points: int = MAX_GEOMETRY_POINTS,
) -> list[tuple[float, float]]:
    """Evenly downsample geometry while always keeping the first and last points."""

    if len(coordinates) <= max_points:
        return list(coordinates)

    if max_points < 2:
        raise ValueError("max_points must be at least 2")

    last_index = len(coordinates) - 1
    selected_indices = {
        round(index * last_index / (max_points - 1)) for index in range(max_points)
    }
    selected_indices.add(0)
    selected_indices.add(last_index)
    ordered_indices = sorted(selected_indices)

    downsampled = [coordinates[index] for index in ordered_indices]
    if len(downsampled) > max_points:
        trimmed = downsampled[: max_points - 1]
        trimmed.append(coordinates[-1])
        return trimmed
    return downsampled


def _validate_departure(departure: datetime) -> None:
    """Validate that departure is timezone-aware."""

    if departure.tzinfo is None or departure.utcoffset() is None:
        raise ValueError("departure must be timezone-aware")


def _validate_load_weight(load_weight_lb: float) -> None:
    """Validate that load weight is non-negative."""

    if load_weight_lb < 0:
        raise ValueError("load_weight_lb cannot be negative")


def _iso_utc(value: datetime) -> str:
    """Return an ISO-8601 string normalized to UTC."""

    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _rounded_geometry(coordinates: Sequence[tuple[float, float]]) -> list[list[float]]:
    """Round geometry coordinates for JSON output."""

    return [
        [round(lat, COORDINATE_ROUND_DIGITS), round(lon, COORDINATE_ROUND_DIGITS)]
        for lat, lon in downsample_geometry(coordinates)
    ]


def _serialize_summary(summary: object) -> dict[str, object]:
    """Serialize a route summary for API output."""

    route_summary = summary
    return {
        "miles_by_level": {
            level.name: round(route_summary.miles_by_level[level], MILES_ROUND_DIGITS)
            for level in RiskLevel
        },
        "worst_level": route_summary.worst_level.name,
        "average_risk": round(route_summary.average_risk, AVERAGE_RISK_ROUND_DIGITS),
        "has_no_travel": route_summary.has_no_travel,
    }


def _serialize_checkpoint(
    checkpoint: Checkpoint,
    assessment: RiskAssessment,
    weather: WeatherConditions,
) -> dict[str, object]:
    """Serialize one analyzed checkpoint for API output."""

    return {
        "index": checkpoint.index,
        "mile_marker": round(checkpoint.mile_marker, MILES_ROUND_DIGITS),
        "lat": round(checkpoint.lat, COORDINATE_ROUND_DIGITS),
        "lon": round(checkpoint.lon, COORDINATE_ROUND_DIGITS),
        "eta": _iso_utc(checkpoint.eta),
        "level": assessment.level.name,
        "reasons": list(assessment.reasons),
        "weather": {
            "wind_mph": round(weather.wind_mph, WEATHER_ROUND_DIGITS),
            "rain_in_hr": round(weather.rain_in_hr, WEATHER_ROUND_DIGITS),
            "snow_in_hr": round(weather.snow_in_hr, WEATHER_ROUND_DIGITS),
        },
    }


def analyze_trip(
    origin: tuple[float, float],
    destination: tuple[float, float],
    departure: datetime,
    load_weight_lb: float,
    interval_miles: int | None = None,
    origin_timezone: str | None = None,
) -> dict[str, object]:
    """Analyze route alternatives and return a JSON-serialisable recommendation."""

    _validate_departure(departure)
    _validate_load_weight(load_weight_lb)

    routes = get_routes(origin, destination)

    route_checkpoints: dict[str, list[Checkpoint]] = {}
    route_intervals: dict[str, int] = {}
    all_points: list[tuple[float, float]] = []
    latest_eta = departure

    for route in routes:
        chosen_interval = interval_miles or choose_interval_miles(route.distance_miles)
        checkpoints = generate_checkpoints(
            route.coordinates,
            route.distance_miles,
            route.duration_seconds,
            departure,
            chosen_interval,
        )
        route_intervals[route.route_id] = chosen_interval
        route_checkpoints[route.route_id] = checkpoints
        all_points.extend((checkpoint.lat, checkpoint.lon) for checkpoint in checkpoints)
        if checkpoints:
            latest_eta = max(latest_eta, checkpoints[-1].eta)

    start_date = departure.astimezone(timezone.utc).date()
    end_date = latest_eta.astimezone(timezone.utc).date()
    all_forecasts = fetch_forecasts(all_points, start=start_date, end=end_date)

    demo_mode_active = is_demo_mode_active()
    route_assessments: dict[str, list[RiskAssessment]] = {}
    route_conditions: dict[str, list[WeatherConditions]] = {}
    forecast_index = 0

    for route in routes:
        checkpoints = route_checkpoints[route.route_id]
        checkpoint_count = len(checkpoints)
        forecasts = all_forecasts[forecast_index : forecast_index + checkpoint_count]
        forecast_index += checkpoint_count
        assessments: list[RiskAssessment] = []
        checkpoint_conditions: list[WeatherConditions] = []
        for checkpoint, forecast in zip(checkpoints, forecasts, strict=True):
            conditions = conditions_at(forecast, checkpoint.eta)
            if demo_mode_active:
                hour_offset = int((checkpoint.eta - departure).total_seconds() // 3600)
                hour_offset = max(0, min(47, hour_offset))
                conditions = WeatherConditions(**apply_demo_weather(
                    {
                        "wind_mph": conditions.wind_mph,
                        "rain_in_hr": conditions.rain_in_hr,
                        "snow_in_hr": conditions.snow_in_hr,
                    },
                    checkpoint.mile_marker,
                    hour_offset,
                ))
            checkpoint_conditions.append(conditions)
            assessments.append(assess_risk(conditions, load_weight_lb))
        route_assessments[route.route_id] = assessments
        route_conditions[route.route_id] = checkpoint_conditions

    summaries = [
        summarize_route(
            route.route_id,
            route.distance_miles,
            route.duration_seconds,
            route_checkpoints[route.route_id],
            route_assessments[route.route_id],
        )
        for route in routes
    ]
    ranked_summaries = rank_routes(summaries)
    explanation = explain_recommendation(ranked_summaries)
    summary_by_route_id = {summary.route_id: summary for summary in ranked_summaries}
    route_by_id = {route.route_id: route for route in routes}

    serialized_routes: list[dict[str, object]] = []
    for rank, summary in enumerate(ranked_summaries, start=1):
        route = route_by_id[summary.route_id]
        checkpoints = route_checkpoints[route.route_id]
        assessments = route_assessments[route.route_id]
        conditions = route_conditions[route.route_id]
        serialized_routes.append(
            {
                "route_id": route.route_id,
                "rank": rank,
                "is_recommended": rank == 1,
                "is_generated": route.is_generated,
                "distance_miles": round(route.distance_miles, MILES_ROUND_DIGITS),
                "duration_seconds": round(route.duration_seconds),
                "arrival": _iso_utc(departure + timedelta(seconds=route.duration_seconds)),
                "interval_miles": route_intervals[route.route_id],
                "summary": _serialize_summary(summary_by_route_id[route.route_id]),
                "geometry": _rounded_geometry(route.coordinates),
                "checkpoints": [
                    _serialize_checkpoint(checkpoint, assessment, weather)
                    for checkpoint, assessment, weather in zip(
                        checkpoints,
                        assessments,
                        conditions,
                        strict=True,
                    )
                ],
            }
        )

    result = {
        "recommended_route_id": ranked_summaries[0].route_id,
        "explanation": explanation,
        "load_weight_lb": float(load_weight_lb),
        "departure": _iso_utc(departure),
        "origin_timezone": origin_timezone,
        "routes": serialized_routes,
    }
    if demo_mode_active:
        result["demo_mode"] = True
    return result