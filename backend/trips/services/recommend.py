"""Route risk summarization, ranking, and recommendation text."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from trips.services.checkpoints import Checkpoint
from trips.services.risk import RiskAssessment, RiskLevel


MILES_ROUND_DIGITS: int = 1
AVERAGE_RISK_ROUND_DIGITS: int = 2
DURATION_MINUTES_ROUND_DIVISOR: float = 60.0


@dataclass(frozen=True)
class RouteSummary:
    """Risk summary values used to compare route options."""

    route_id: str
    distance_miles: float
    duration_seconds: float
    miles_by_level: dict[RiskLevel, float]
    worst_level: RiskLevel
    average_risk: float
    no_travel_miles: float
    severe_miles: float
    high_miles: float
    has_no_travel: bool


def _empty_miles_by_level() -> dict[RiskLevel, float]:
    """Create a zero-filled mileage dictionary for all risk levels."""

    return {level: 0.0 for level in RiskLevel}


def summarize_route(
    route_id: str,
    distance_miles: float,
    duration_seconds: float,
    checkpoints: Sequence[Checkpoint],
    assessments: Sequence[RiskAssessment],
) -> RouteSummary:
    """Summarize checkpoint assessments into route-level risk metrics."""

    if not checkpoints or not assessments:
        raise ValueError("checkpoints and assessments must be non-empty")
    if len(checkpoints) != len(assessments):
        raise ValueError("checkpoints and assessments must be the same length")

    miles_by_level = _empty_miles_by_level()
    worst_level = RiskLevel.LOW
    weighted_total = 0.0
    segment_total = 0.0
    has_no_travel = False

    for checkpoint, assessment in zip(checkpoints, assessments, strict=True):
        level = assessment.level
        miles_by_level[level] += checkpoint.segment_miles
        weighted_total += checkpoint.segment_miles * int(level)
        segment_total += checkpoint.segment_miles
        worst_level = max(worst_level, level)
        if level == RiskLevel.NO_TRAVEL:
            has_no_travel = True

    if segment_total == 0.0:
        average_risk = float(int(assessments[0].level))
    else:
        average_risk = weighted_total / segment_total

    return RouteSummary(
        route_id=route_id,
        distance_miles=distance_miles,
        duration_seconds=duration_seconds,
        miles_by_level=miles_by_level,
        worst_level=worst_level,
        average_risk=average_risk,
        no_travel_miles=miles_by_level[RiskLevel.NO_TRAVEL],
        severe_miles=miles_by_level[RiskLevel.SEVERE],
        high_miles=miles_by_level[RiskLevel.HIGH],
        has_no_travel=has_no_travel,
    )


def _rounded_miles(value: float) -> float:
    """Round mileage values for stable ranking comparisons."""

    return round(value, MILES_ROUND_DIGITS)


def _rounded_average_risk(value: float) -> float:
    """Round average risk values for stable ranking comparisons."""

    return round(value, AVERAGE_RISK_ROUND_DIGITS)


def _rounded_duration_minutes(value: float) -> int:
    """Round duration to whole minutes for stable ranking comparisons."""

    return round(value / DURATION_MINUTES_ROUND_DIVISOR)


def _sort_key(summary: RouteSummary) -> tuple[bool, float, float, float, float, int]:
    """Return the rounded stable comparison key for a route summary."""

    return (
        summary.has_no_travel,
        _rounded_miles(summary.no_travel_miles),
        _rounded_miles(summary.severe_miles),
        _rounded_miles(summary.high_miles),
        _rounded_average_risk(summary.average_risk),
        _rounded_duration_minutes(summary.duration_seconds),
    )


def rank_routes(summaries: Sequence[RouteSummary]) -> list[RouteSummary]:
    """Rank route summaries from best to worst using rounded criteria."""

    return sorted(summaries, key=_sort_key)


def _display_route_name(summary: RouteSummary) -> str:
    """Return a human-readable route label."""

    return summary.route_id.replace("route-", "Route ")


def explain_recommendation(ranked: Sequence[RouteSummary]) -> str:
    """Explain briefly why the top-ranked route is preferred."""

    if not ranked:
        raise ValueError("ranked must be non-empty")

    winner = ranked[0]
    if len(ranked) == 1:
        return f"{_display_route_name(winner)} is the only available route."

    runner_up = ranked[1]

    if winner.has_no_travel:
        return (
            "Every route has a No Travel segment; "
            f"{_display_route_name(winner)} has the least at "
            f"{_rounded_miles(winner.no_travel_miles):.1f} miles."
        )

    if winner.has_no_travel != runner_up.has_no_travel:
        return (
            f"{_display_route_name(winner)} avoids No Travel segments; "
            f"{_display_route_name(runner_up)} includes one."
        )

    winner_no_travel = _rounded_miles(winner.no_travel_miles)
    runner_no_travel = _rounded_miles(runner_up.no_travel_miles)
    if winner_no_travel != runner_no_travel:
        return (
            f"{_display_route_name(winner)} has {winner_no_travel:.1f} No Travel miles "
            f"vs {runner_no_travel:.1f} on {_display_route_name(runner_up)}."
        )

    winner_severe = _rounded_miles(winner.severe_miles)
    runner_severe = _rounded_miles(runner_up.severe_miles)
    if winner_severe != runner_severe:
        return (
            f"{_display_route_name(winner)} has {winner_severe:.1f} Severe miles "
            f"vs {runner_severe:.1f} on {_display_route_name(runner_up)}."
        )

    winner_high = _rounded_miles(winner.high_miles)
    runner_high = _rounded_miles(runner_up.high_miles)
    if winner_high != runner_high:
        return (
            f"{_display_route_name(winner)} has {winner_high:.1f} High miles "
            f"vs {runner_high:.1f} on {_display_route_name(runner_up)}."
        )

    winner_average = _rounded_average_risk(winner.average_risk)
    runner_average = _rounded_average_risk(runner_up.average_risk)
    if winner_average != runner_average:
        return (
            f"{_display_route_name(winner)} has lower average weather risk "
            f"({winner_average:.2f} vs {runner_average:.2f})."
        )

    winner_duration = _rounded_duration_minutes(winner.duration_seconds)
    runner_duration = _rounded_duration_minutes(runner_up.duration_seconds)
    if winner_duration != runner_duration:
        return "Fastest route; weather risk is equivalent."

    return "Routes are effectively tied on weather risk and travel time."