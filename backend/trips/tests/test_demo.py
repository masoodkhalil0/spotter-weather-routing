from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from trips.services.checkpoints import generate_checkpoints
from trips.services.demo import apply_demo_weather, is_demo_mode_active
from trips.services.heatmap import build_heatmap
from trips.services.risk import RiskLevel, WeatherConditions, assess_risk
from trips.services.routing import Route
from trips.services.weather import HourlyForecast


def _conditions_from_dict(values: dict[str, float]) -> WeatherConditions:
    return WeatherConditions(
        wind_mph=values["wind_mph"],
        rain_in_hr=values["rain_in_hr"],
        snow_in_hr=values["snow_in_hr"],
    )


def _route() -> Route:
    return Route(
        route_id="route-1",
        coordinates=((40.0, -75.0), (41.0, -74.0)),
        distance_miles=120.0,
        duration_seconds=7200.0,
        is_generated=False,
    )


def _forecast_for(when: datetime, *, wind: float = 10.0, rain: float = 0.0, snow: float = 0.0) -> HourlyForecast:
    return HourlyForecast(
        times=(when.astimezone(timezone.utc),),
        wind_mph=(wind,),
        rain_in=(rain,),
        snow_in=(snow,),
    )


class DemoWeatherTests(SimpleTestCase):
    def test_apply_demo_weather_is_deterministic_for_same_inputs(self) -> None:
        weather = {"wind_mph": 12.0, "rain_in_hr": 0.1, "snow_in_hr": 0.0}

        first = apply_demo_weather(weather, 150.0, 7)
        second = apply_demo_weather(weather, 150.0, 7)

        self.assertEqual(first, second)

    def test_apply_demo_weather_output_stays_within_supported_ranges(self) -> None:
        for mile_marker in range(0, 601, 25):
            for hour_offset in range(48):
                result = apply_demo_weather({"wind_mph": 0.0, "rain_in_hr": 0.0, "snow_in_hr": 0.0}, mile_marker, hour_offset)
                self.assertGreaterEqual(result["wind_mph"], 5.0)
                self.assertLessEqual(result["wind_mph"], 60.0)
                self.assertGreaterEqual(result["rain_in_hr"], 0.0)
                self.assertLessEqual(result["rain_in_hr"], 1.2)
                self.assertGreaterEqual(result["snow_in_hr"], 0.0)
                self.assertLessEqual(result["snow_in_hr"], 3.5)

    def test_apply_demo_weather_reaches_all_five_risk_levels_for_20000_lb(self) -> None:
        seen_levels: set[RiskLevel] = set()

        for mile_marker in range(0, 901, 15):
            for hour_offset in range(48):
                weather = apply_demo_weather({"wind_mph": 0.0, "rain_in_hr": 0.0, "snow_in_hr": 0.0}, mile_marker, hour_offset)
                seen_levels.add(assess_risk(_conditions_from_dict(weather), 20000.0).level)

        self.assertEqual(seen_levels, set(RiskLevel))

    def test_apply_demo_weather_keeps_real_higher_values(self) -> None:
        original = {"wind_mph": 59.0, "rain_in_hr": 1.1, "snow_in_hr": 3.4}

        result = apply_demo_weather(original, 10.0, 1)

        self.assertEqual(result, original)

    def test_demo_sweep_level_shares_are_balanced(self) -> None:
        counts = {level: 0 for level in RiskLevel}
        total_samples = 0

        for mile_marker in range(0, 1001, 10):
            for hour_offset in range(48):
                weather = apply_demo_weather({"wind_mph": 0.0, "rain_in_hr": 0.0, "snow_in_hr": 0.0}, mile_marker, hour_offset)
                level = assess_risk(_conditions_from_dict(weather), 20000.0).level
                counts[level] += 1
                total_samples += 1

        shares = {level: counts[level] / total_samples for level in RiskLevel}

        self.assertGreaterEqual(shares[RiskLevel.LOW], 0.25)
        self.assertLessEqual(shares[RiskLevel.LOW], 0.45)
        self.assertGreaterEqual(shares[RiskLevel.MODERATE], 0.15)
        self.assertLessEqual(shares[RiskLevel.MODERATE], 0.35)
        self.assertGreaterEqual(shares[RiskLevel.HIGH], 0.10)
        self.assertLessEqual(shares[RiskLevel.HIGH], 0.30)
        self.assertGreaterEqual(shares[RiskLevel.SEVERE], 0.05)
        self.assertLessEqual(shares[RiskLevel.SEVERE], 0.20)
        self.assertGreaterEqual(shares[RiskLevel.NO_TRAVEL], 0.01)
        self.assertLessEqual(shares[RiskLevel.NO_TRAVEL], 0.10)

    def test_demo_sweep_has_calm_stretch(self) -> None:
        has_calm_stretch = False

        for mile_marker in range(0, 1001, 10):
            if any(
                assess_risk(
                    _conditions_from_dict(apply_demo_weather({"wind_mph": 0.0, "rain_in_hr": 0.0, "snow_in_hr": 0.0}, mile_marker, hour_offset)),
                    20000.0,
                ).level == RiskLevel.LOW
                for hour_offset in range(48)
            ):
                has_calm_stretch = True
                break

        self.assertTrue(has_calm_stretch)


class DemoModeSettingsTests(SimpleTestCase):
    @override_settings(DEBUG=False, DEMO_MODE=True)
    def test_is_demo_mode_active_is_false_when_debug_is_false(self) -> None:
        self.assertFalse(is_demo_mode_active())

    @override_settings(DEBUG=True, DEMO_MODE=True)
    def test_is_demo_mode_active_is_true_when_debug_and_demo_mode_are_true(self) -> None:
        self.assertTrue(is_demo_mode_active())

    @override_settings(DEBUG=True, DEMO_MODE=False)
    def test_is_demo_mode_active_is_false_when_demo_mode_is_false(self) -> None:
        self.assertFalse(is_demo_mode_active())


class DemoModeApiTests(APITestCase):
    def setUp(self) -> None:
        self.analyze_url = reverse("api-analyze")
        self.departure = (datetime.now(timezone.utc) + timedelta(hours=2)).replace(microsecond=0)

    def _payload(self) -> dict[str, object]:
        return {
            "origin": {"lat": 40.0, "lon": -75.0},
            "destination": {"lat": 41.0, "lon": -74.0},
            "departure": self.departure.isoformat(),
            "load_weight_lb": 20000.0,
            "interval_miles": 50,
        }

    @patch("trips.api.views.lookup_timezone")
    @patch("trips.services.analysis.fetch_forecasts")
    @patch("trips.services.analysis.get_routes")
    @override_settings(DEBUG=True, DEMO_MODE=False)
    def test_analyze_response_omits_demo_mode_key_when_disabled(self, mock_get_routes, mock_fetch_forecasts, mock_lookup_timezone) -> None:
        route = _route()
        checkpoints = generate_checkpoints(route.coordinates, route.distance_miles, route.duration_seconds, self.departure, 50)
        mock_lookup_timezone.return_value = {"timezone": "America/New_York", "utc_offset_minutes": -240}
        mock_get_routes.return_value = [route]
        mock_fetch_forecasts.return_value = [_forecast_for(checkpoint.eta, wind=10.0) for checkpoint in checkpoints]

        response = self.client.post(self.analyze_url, data=self._payload(), format="json")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("demo_mode", response.json())

    @patch("trips.api.views.lookup_timezone")
    @patch("trips.services.analysis.fetch_forecasts")
    @patch("trips.services.analysis.get_routes")
    @override_settings(DEBUG=True, DEMO_MODE=True)
    def test_analyze_response_includes_demo_mode_key_when_enabled(self, mock_get_routes, mock_fetch_forecasts, mock_lookup_timezone) -> None:
        route = _route()
        checkpoints = generate_checkpoints(route.coordinates, route.distance_miles, route.duration_seconds, self.departure, 50)
        mock_lookup_timezone.return_value = {"timezone": "America/New_York", "utc_offset_minutes": -240}
        mock_get_routes.return_value = [route]
        mock_fetch_forecasts.return_value = [_forecast_for(checkpoint.eta, wind=10.0) for checkpoint in checkpoints]

        response = self.client.post(self.analyze_url, data=self._payload(), format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get("demo_mode"), True)

    @patch("trips.api.views.lookup_timezone")
    @patch("trips.services.analysis.fetch_forecasts")
    @patch("trips.services.analysis.get_routes")
    @override_settings(DEBUG=False, DEMO_MODE=True)
    def test_analyze_response_omits_demo_mode_key_when_debug_is_false_even_if_demo_mode_is_true(self, mock_get_routes, mock_fetch_forecasts, mock_lookup_timezone) -> None:
        route = _route()
        checkpoints = generate_checkpoints(route.coordinates, route.distance_miles, route.duration_seconds, self.departure, 50)
        mock_lookup_timezone.return_value = {"timezone": "America/New_York", "utc_offset_minutes": -240}
        mock_get_routes.return_value = [route]
        mock_fetch_forecasts.return_value = [_forecast_for(checkpoint.eta, wind=10.0) for checkpoint in checkpoints]

        response = self.client.post(self.analyze_url, data=self._payload(), format="json")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("demo_mode", response.json())


class DemoModeHeatmapTests(SimpleTestCase):
    def setUp(self) -> None:
        self.route = _route()
        self.departure = (datetime.now(timezone.utc) + timedelta(hours=2)).replace(minute=0, second=0, microsecond=0)

    @patch("trips.services.heatmap.fetch_forecasts")
    @override_settings(DEBUG=True, DEMO_MODE=True)
    def test_build_heatmap_includes_demo_mode_only_when_active(self, mock_fetch_forecasts) -> None:
        mock_fetch_forecasts.return_value = [_forecast_for(self.departure, wind=10.0) for _ in range(2)]

        with patch("trips.api.views.lookup_timezone", return_value={"timezone": "America/New_York", "utc_offset_minutes": -240}):
            enabled_result = build_heatmap([self.route], self.departure, 20000.0, hours=1, max_points=2, origin_timezone="America/New_York")

        self.assertEqual(enabled_result.get("demo_mode"), True)

        with override_settings(DEBUG=True, DEMO_MODE=False):
            with patch("trips.services.heatmap.fetch_forecasts", return_value=[_forecast_for(self.departure, wind=10.0) for _ in range(2)]):
                disabled_result = build_heatmap([self.route], self.departure, 20000.0, hours=1, max_points=2, origin_timezone="America/New_York")

        self.assertNotIn("demo_mode", disabled_result)