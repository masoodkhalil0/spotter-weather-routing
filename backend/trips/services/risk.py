"""Pure-Python weather risk classification.

Boundary rule: thresholds use lower-bound inclusive and upper-bound exclusive
bands, except the top rain and snow bands which are strictly greater-than.
For example, wind 35.0 is HIGH, rain 1.00 is SEVERE, snow 3.0 is SEVERE,
and wind 55.0 is NO_TRAVEL.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


WIND_MODERATE_MIN_MPH: float = 25.0
WIND_HIGH_MIN_MPH: float = 35.0
WIND_SEVERE_MIN_MPH: float = 45.0
WIND_NO_TRAVEL_MIN_MPH: float = 55.0

RAIN_MODERATE_MIN_IN_PER_HR: float = 0.10
RAIN_HIGH_MIN_IN_PER_HR: float = 0.25
RAIN_SEVERE_MIN_IN_PER_HR: float = 0.50
RAIN_NO_TRAVEL_GT_IN_PER_HR: float = 1.00

SNOW_MODERATE_MIN_IN_PER_HR: float = 0.5
SNOW_HIGH_MIN_IN_PER_HR: float = 1.0
SNOW_SEVERE_MIN_IN_PER_HR: float = 2.0
SNOW_NO_TRAVEL_GT_IN_PER_HR: float = 3.0

LOAD_NO_TRAVEL_WIND_MIN_MPH: float = 45.0
LOAD_NO_TRAVEL_WIND_MAX_MPH: float = 55.0
LOAD_NO_TRAVEL_WEIGHT_GT_LB: float = 30000.0
LOAD_SEVERE_WIND_MIN_MPH: float = 35.0
LOAD_SEVERE_WIND_MAX_MPH: float = 45.0
LOAD_SEVERE_WEIGHT_GT_LB: float = 40000.0


class RiskLevel(IntEnum):
    """Ordered overall risk levels."""

    LOW = 1
    MODERATE = 2
    HIGH = 3
    SEVERE = 4
    NO_TRAVEL = 5


@dataclass(frozen=True)
class WeatherConditions:
    """Weather inputs used for risk assessment."""

    wind_mph: float
    rain_in_hr: float
    snow_in_hr: float


@dataclass(frozen=True)
class RiskAssessment:
    """Detailed risk assessment result."""

    level: RiskLevel
    wind: RiskLevel
    rain: RiskLevel
    snow: RiskLevel
    reasons: tuple[str, ...]


def _validate_non_negative(value: float, name: str) -> None:
    """Raise ValueError when a numeric input is negative."""

    if value < 0:
        raise ValueError(f"{name} cannot be negative")


def classify_wind(mph: float) -> RiskLevel:
    """Classify wind risk from miles per hour."""

    _validate_non_negative(mph, "wind_mph")

    if mph >= WIND_NO_TRAVEL_MIN_MPH:
        return RiskLevel.NO_TRAVEL
    if mph >= WIND_SEVERE_MIN_MPH:
        return RiskLevel.SEVERE
    if mph >= WIND_HIGH_MIN_MPH:
        return RiskLevel.HIGH
    if mph >= WIND_MODERATE_MIN_MPH:
        return RiskLevel.MODERATE
    return RiskLevel.LOW


def classify_rain(in_hr: float) -> RiskLevel:
    """Classify rain risk from inches per hour."""

    _validate_non_negative(in_hr, "rain_in_hr")

    if in_hr > RAIN_NO_TRAVEL_GT_IN_PER_HR:
        return RiskLevel.NO_TRAVEL
    if in_hr >= RAIN_SEVERE_MIN_IN_PER_HR:
        return RiskLevel.SEVERE
    if in_hr >= RAIN_HIGH_MIN_IN_PER_HR:
        return RiskLevel.HIGH
    if in_hr >= RAIN_MODERATE_MIN_IN_PER_HR:
        return RiskLevel.MODERATE
    return RiskLevel.LOW


def classify_snow(in_hr: float) -> RiskLevel:
    """Classify snow risk from inches per hour."""

    _validate_non_negative(in_hr, "snow_in_hr")

    if in_hr > SNOW_NO_TRAVEL_GT_IN_PER_HR:
        return RiskLevel.NO_TRAVEL
    if in_hr >= SNOW_SEVERE_MIN_IN_PER_HR:
        return RiskLevel.SEVERE
    if in_hr >= SNOW_HIGH_MIN_IN_PER_HR:
        return RiskLevel.HIGH
    if in_hr >= SNOW_MODERATE_MIN_IN_PER_HR:
        return RiskLevel.MODERATE
    return RiskLevel.LOW


def assess_risk(conditions: WeatherConditions, load_weight_lb: float) -> RiskAssessment:
    """Assess combined weather and load-based travel risk."""

    _validate_non_negative(load_weight_lb, "load_weight_lb")

    wind_risk = classify_wind(conditions.wind_mph)
    rain_risk = classify_rain(conditions.rain_in_hr)
    snow_risk = classify_snow(conditions.snow_in_hr)

    reasons: list[str] = []

    if wind_risk >= RiskLevel.MODERATE:
        reasons.append(
            f"Wind at {conditions.wind_mph} mph is {wind_risk.name.replace('_', ' ').lower()}."
        )
    if rain_risk >= RiskLevel.MODERATE:
        reasons.append(
            f"Rain at {conditions.rain_in_hr} in/hr is {rain_risk.name.replace('_', ' ').lower()}."
        )
    if snow_risk >= RiskLevel.MODERATE:
        reasons.append(
            f"Snow at {conditions.snow_in_hr} in/hr is {snow_risk.name.replace('_', ' ').lower()}."
        )

    level = max(wind_risk, rain_risk, snow_risk)

    if (
        LOAD_NO_TRAVEL_WIND_MIN_MPH <= conditions.wind_mph < LOAD_NO_TRAVEL_WIND_MAX_MPH
        and load_weight_lb > LOAD_NO_TRAVEL_WEIGHT_GT_LB
    ):
        level = max(level, RiskLevel.NO_TRAVEL)
        reasons.append(
            "Load rule triggered: wind between 45 and 54.9 mph with load over 30,000 lb is no travel."
        )

    if (
        LOAD_SEVERE_WIND_MIN_MPH <= conditions.wind_mph < LOAD_SEVERE_WIND_MAX_MPH
        and load_weight_lb > LOAD_SEVERE_WEIGHT_GT_LB
    ):
        level = max(level, RiskLevel.SEVERE)
        reasons.append(
            "Load rule triggered: wind between 35 and 44.9 mph with load over 40,000 lb is at least severe."
        )

    return RiskAssessment(
        level=level,
        wind=wind_risk,
        rain=rain_risk,
        snow=snow_risk,
        reasons=tuple(reasons),
    )