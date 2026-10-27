from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from trips.services.heatmap import build_heatmap
from trips.services.routing import Route
from trips.services.weather import HourlyForecast


def _route(route_id: str, coordinates: tuple[tuple[float, float], ...], distance_miles: float = 100.0) -> Route:
    return Route(
        route_id=route_id,
        coordinates=coordinates,
        distance_miles=distance_miles,
        duration_seconds=7200.0,
        is_generated=False,
    )


def _forecast_series(start: datetime, hours: int, *, wind: float, rain: float = 0.0, snow: float = 0.0) -> HourlyForecast:
    times = tuple(start + timedelta(hours=index) for index in range(hours))
    return HourlyForecast(
        times=times,
        wind_mph=tuple(wind for _ in range(hours)),
        rain_in=tuple(rain for _ in range(hours)),
        snow_in=tuple(snow for _ in range(hours)),
    )


class HeatmapTests(SimpleTestCase):
    def setUp(self) -> None:
        self.departure = datetime(2026, 1, 1, 10, 37, 45, tzinfo=timezone.utc)
        self.route = _route("route-1", ((40.0, -75.0), (41.0, -74.0)))

    def test_invalid_inputs_raise_value_error(self) -> None:
        with self.assertRaisesMessage(ValueError, "departure must be timezone-aware"):
            build_heatmap([self.route], datetime(2026, 1, 1, 10, 0), 1000.0)

        with self.assertRaisesMessage(ValueError, "load_weight_lb cannot be negative"):
            build_heatmap([self.route], self.departure, -1.0)

        with self.assertRaisesMessage(ValueError, "hours must be between 1 and 49"):
            build_heatmap([self.route], self.departure, 1000.0, hours=0)

    @patch("trips.services.heatmap.fetch_forecasts")
    def test_grid_cap_dedupe_and_single_forecast_fetch(self, mock_fetch_forecasts: Mock) -> None:
        overlapping_a = _route("route-1", ((40.0, -75.0), (40.5, -74.5), (41.0, -74.0)))
        overlapping_b = _route("route-2", ((40.02, -75.02), (40.52, -74.48), (41.02, -73.98)))
        start_time = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
        mock_fetch_forecasts.return_value = [_forecast_series(start_time, 4, wind=10.0) for _ in range(3)]

        result = build_heatmap([overlapping_a, overlapping_b], self.departure, 1000.0, hours=4, max_points=3)

        self.assertEqual(len(result["points"]), 3)
        mock_fetch_forecasts.assert_called_once()
        fetched_points = mock_fetch_forecasts.call_args.args[0]
        self.assertEqual(len(fetched_points), 3)

    @patch("trips.services.heatmap.fetch_forecasts")
    def test_levels_have_expected_length_and_integer_range(self, mock_fetch_forecasts: Mock) -> None:
        start_time = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
        mock_fetch_forecasts.return_value = [_forecast_series(start_time, 5, wind=35.0) for _ in range(2)]

        result = build_heatmap([self.route], self.departure, 20000.0, hours=5, max_points=2)

        levels = result["points"][0]["levels"]
        self.assertEqual(len(levels), 5)
        self.assertTrue(all(level in {1, 2, 3, 4, 5} for level in levels if level is not None))

    @patch("trips.services.heatmap.fetch_forecasts")
    def test_heavy_load_turns_40_mph_hour_severe_while_light_load_is_high(self, mock_fetch_forecasts: Mock) -> None:
        start_time = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
        mock_fetch_forecasts.return_value = [_forecast_series(start_time, 3, wind=40.0) for _ in range(2)]

        heavy = build_heatmap([self.route], self.departure, 45000.0, hours=3, max_points=2)
        light = build_heatmap([self.route], self.departure, 20000.0, hours=3, max_points=2)

        self.assertEqual(heavy["points"][0]["levels"][0], 4)
        self.assertEqual(light["points"][0]["levels"][0], 3)

    @patch("trips.services.heatmap.fetch_forecasts")
    def test_missing_hour_slot_yields_none_without_failing(self, mock_fetch_forecasts: Mock) -> None:
        start_time = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
        mock_fetch_forecasts.return_value = [_forecast_series(start_time, 1, wind=10.0) for _ in range(2)]

        result = build_heatmap([self.route], self.departure, 20000.0, hours=4, max_points=2)

        point = result["points"][0]
        self.assertEqual(point["levels"], [1, 1, None, None])
        self.assertEqual(point["wind"], [10.0, 10.0, None, None])
        self.assertEqual(point["rain"], [0.0, 0.0, None, None])
        self.assertEqual(point["snow"], [0.0, 0.0, None, None])

    @patch("trips.services.heatmap.fetch_forecasts")
    def test_result_is_json_serialisable(self, mock_fetch_forecasts: Mock) -> None:
        start_time = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
        mock_fetch_forecasts.return_value = [_forecast_series(start_time, 2, wind=10.0) for _ in range(2)]

        result = build_heatmap([self.route], self.departure, 1000.0, hours=2, max_points=2)

        self.assertIsInstance(json.dumps(result), str)