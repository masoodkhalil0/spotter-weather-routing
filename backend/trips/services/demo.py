"""Dev-only weather overrides for demos."""

from __future__ import annotations

from django.conf import settings

from math import pi, sin


def is_demo_mode_active() -> bool:
    """Return whether demo mode is active; demo is active only when DEBUG is True."""

    return bool(settings.DEBUG and settings.DEMO_MODE)


def apply_demo_weather(weather: dict[str, float], mile_marker: float, hour_offset: int) -> dict[str, float]:
    """Return demo-only weather overrides as a new dict for development demos."""

    route_wave = (sin((mile_marker / 120.0) + (hour_offset / 6.0)) + 1.0) / 2.0
    time_wave = (sin((hour_offset / 4.8) - (mile_marker / 210.0) + (pi / 6.0)) + 1.0) / 2.0
    cross_wave = (sin((mile_marker / 55.0) - (hour_offset / 2.7) + (pi / 3.0)) + 1.0) / 2.0
    blend = (0.45 * route_wave) + (0.35 * time_wave) + (0.20 * cross_wave)
    calm_blend = blend ** 1.8

    peak_wave = (sin((mile_marker / 38.0) + (hour_offset / 2.4) - (pi / 7.0)) + 1.0) / 2.0
    sharp_peak = peak_wave ** 7

    warm_phase = (sin((mile_marker / 78.0) + (hour_offset / 4.9)) + 1.0) / 2.0
    cold_phase = (sin((mile_marker / 82.0) - (hour_offset / 5.2) + pi) + 1.0) / 2.0
    rain_bias = max(0.0, warm_phase - 0.42) / 0.58
    snow_bias = max(0.0, cold_phase - 0.42) / 0.58
    rain_bias *= 1.0 - (0.65 * snow_bias)
    snow_bias *= 1.0 - (0.65 * rain_bias)

    demo_wind = 5.0 + (41.0 * calm_blend) + (30.0 * sharp_peak)
    demo_rain = min(1.2, (0.78 * calm_blend * rain_bias) + (0.55 * sharp_peak * max(rain_bias, 0.25)))
    demo_snow = min(3.5, (2.15 * calm_blend * snow_bias) + (1.1 * sharp_peak * max(snow_bias, 0.2)))

    return {
        "wind_mph": max(float(weather.get("wind_mph", 0.0)), min(60.0, demo_wind)),
        "rain_in_hr": max(float(weather.get("rain_in_hr", 0.0)), min(1.2, demo_rain)),
        "snow_in_hr": max(float(weather.get("snow_in_hr", 0.0)), min(3.5, demo_snow)),
    }