"""Dev-only weather overrides for demos."""

from __future__ import annotations

from django.conf import settings

from math import pi, sin


def is_demo_mode_active() -> bool:
    """Return whether demo mode is active; demo is active only when DEBUG is True."""

    return bool(settings.DEBUG and settings.DEMO_MODE)


def apply_demo_weather(weather: dict[str, float], mile_marker: float, hour_offset: int) -> dict[str, float]:
    """Return demo-only weather overrides as a new dict for development demos."""

    route_wave = (sin((mile_marker / 85.0) + (hour_offset / 4.0)) + 1.0) / 2.0
    time_wave = (sin((hour_offset / 3.0) - (mile_marker / 140.0) + (pi / 5.0)) + 1.0) / 2.0
    blend = (0.55 * route_wave) + (0.45 * time_wave)

    warm_phase = (sin((mile_marker / 60.0) + (hour_offset / 5.0)) + 1.0) / 2.0
    cold_phase = (sin((mile_marker / 70.0) - (hour_offset / 6.0) + pi) + 1.0) / 2.0
    rain_bias = max(0.0, warm_phase - 0.35) / 0.65
    snow_bias = max(0.0, cold_phase - 0.35) / 0.65

    demo_wind = 5.0 + (55.0 * blend)
    demo_rain = 1.2 * blend * rain_bias
    demo_snow = 3.5 * (1.0 - blend) * snow_bias

    return {
        "wind_mph": max(float(weather.get("wind_mph", 0.0)), min(60.0, demo_wind)),
        "rain_in_hr": max(float(weather.get("rain_in_hr", 0.0)), min(1.2, demo_rain)),
        "snow_in_hr": max(float(weather.get("snow_in_hr", 0.0)), min(3.5, demo_snow)),
    }