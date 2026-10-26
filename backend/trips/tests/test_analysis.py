from __future__ import annotations

from datetime import datetime, timezone
import json
from unittest.mock import Mock, patch

from django.core.cache import cache
from django.test import SimpleTestCase

from trips.services.analysis import analyze_trip, downsample_geometry
from trips.services.checkpoints import choose_interval_miles, generate_checkpoints
from trips.services.risk import RiskLevel
from trips.services.routing import Route
from trips.services.weather import HourlyForecast


def _route(
    route_id: str,
    coordinates: tuple[tuple[float, float], ...],
    distance_miles: float,
    duration_seconds: float,
    is_generated: bool = False,
) -> Route:
    return Route(
        route_id=route_id,
        coordinates=coordinates,
        distance_miles=distance_miles,
        duration_seconds=duration_seconds,
        is_generated=is_generated,
    )


def _forecast(*, hour: int, wind_mph: float, rain_in: float = 0.0, snow_in: float = 0.0) -> HourlyForecast:
    when = datetime(2026, 1, 1, hour, 0, tzinfo=timezone.utc)
    return HourlyForecast(
        times=(when,),
        wind_mph=(wind_mph,),
        rain_in=(rain_in,),
        snow_in=(snow_in,),
    )


def _forecast_for_eta(
    when: datetime,
    wind_mph: float,
    rain_in: float = 0.0,
    snow_in: float = 0.0,
) -> HourlyForecast:
    return HourlyForecast(
        times=(when.astimezone(timezone.utc),),
        wind_mph=(wind_mph,),
        rain_in=(rain_in,),
        snow_in=(snow_in,),
    )


def _route_checkpoints(route: Route, departure: datetime, interval_miles: int | None = None):
    interval = interval_miles or choose_interval_miles(route.distance_miles)
    return generate_checkpoints(route.coordinates, route.distance_miles, route.duration_seconds, departure, interval)


class AnalysisTests(SimpleTestCase):
    def setUp(self) -> None:
        cache.clear()
        self.origin = (40.0, -75.0)
        self.destination = (41.0, -74.0)
        self.departure = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)

    def test_naive_departure_and_negative_weight_raise_value_error(self) -> None:
        with self.assertRaises(ValueError):
            analyze_trip(self.origin, self.destination, datetime(2026, 1, 1, 10, 0), 1000.0)

        with self.assertRaises(ValueError):
            analyze_trip(self.origin, self.destination, self.departure, -1.0)

    @patch("trips.services.analysis.fetch_forecasts")
    @patch("trips.services.analysis.get_routes")
    def test_happy_path_result_shape_and_ranking(self, mock_get_routes: Mock, mock_fetch_forecasts: Mock) -> None:
        routes = [
            _route("route-1", ((40.0, -75.0), (41.0, -74.0)), 100.0, 7200.0, False),
            _route("route-2", ((40.0, -75.0), (40.5, -74.5), (41.0, -74.0)), 120.0, 9000.0, True),
        ]
        route_one_checkpoints = _route_checkpoints(routes[0], self.departure)
        route_two_checkpoints = _route_checkpoints(routes[1], self.departure)
        mock_get_routes.return_value = routes
        mock_fetch_forecasts.return_value = [
            *[_forecast_for_eta(checkpoint.eta, 10.0) for checkpoint in route_one_checkpoints],
            *[_forecast_for_eta(checkpoint.eta, 40.0) for checkpoint in route_two_checkpoints],
        ]

        result = analyze_trip(self.origin, self.destination, self.departure, 20000.0)

        self.assertEqual(set(result.keys()), {"recommended_route_id", "explanation", "load_weight_lb", "departure", "routes"})
        self.assertEqual(result["recommended_route_id"], "route-1")
        self.assertEqual(result["routes"][0]["route_id"], "route-1")
        self.assertEqual(result["routes"][0]["rank"], 1)
        self.assertTrue(result["routes"][0]["is_recommended"])
        self.assertFalse(result["routes"][1]["is_recommended"])
        self.assertEqual(result["routes"][1]["rank"], 2)
        self.assertEqual(result["routes"][0]["summary"]["worst_level"], "LOW")
        self.assertEqual(result["routes"][1]["summary"]["worst_level"], "HIGH")
        self.assertIn("geometry", result["routes"][0])
        self.assertIn("checkpoints", result["routes"][0])

    @patch("trips.services.analysis.fetch_forecasts")
    @patch("trips.services.analysis.get_routes")
    def test_fetch_forecasts_called_once_with_all_checkpoints(
        self,
        mock_get_routes: Mock,
        mock_fetch_forecasts: Mock,
    ) -> None:
        routes = [
            _route("route-1", ((40.0, -75.0), (41.0, -74.0)), 100.0, 7200.0),
            _route("route-2", ((40.0, -75.0), (40.5, -74.5), (41.0, -74.0)), 120.0, 9000.0),
        ]
        route_one_checkpoints = _route_checkpoints(routes[0], self.departure)
        route_two_checkpoints = _route_checkpoints(routes[1], self.departure)
        mock_get_routes.return_value = routes
        mock_fetch_forecasts.return_value = [
            *[_forecast_for_eta(checkpoint.eta, 10.0) for checkpoint in route_one_checkpoints],
            *[_forecast_for_eta(checkpoint.eta, 10.0) for checkpoint in route_two_checkpoints],
        ]

        analyze_trip(self.origin, self.destination, self.departure, 20000.0)

        self.assertEqual(mock_fetch_forecasts.call_count, 1)
        points = mock_fetch_forecasts.call_args.args[0]
        self.assertEqual(len(points), len(route_one_checkpoints) + len(route_two_checkpoints))
        self.assertEqual(mock_fetch_forecasts.call_args.kwargs["start"].isoformat(), "2026-01-01")
        self.assertEqual(mock_fetch_forecasts.call_args.kwargs["end"].isoformat(), "2026-01-01")

    @patch("trips.services.analysis.fetch_forecasts")
    @patch("trips.services.analysis.get_routes")
    def test_heavy_load_makes_40_mph_severe_but_lighter_load_is_high(
        self,
        mock_get_routes: Mock,
        mock_fetch_forecasts: Mock,
    ) -> None:
        route = _route("route-1", ((40.0, -75.0), (41.0, -74.0)), 100.0, 7200.0)
        mock_get_routes.return_value = [route]
        checkpoints = _route_checkpoints(route, self.departure)
        mock_fetch_forecasts.return_value = [_forecast_for_eta(checkpoint.eta, 40.0) for checkpoint in checkpoints]

        heavy = analyze_trip(self.origin, self.destination, self.departure, 45000.0)
        light = analyze_trip(self.origin, self.destination, self.departure, 20000.0)

        self.assertEqual(heavy["routes"][0]["checkpoints"][0]["level"], "SEVERE")
        self.assertEqual(light["routes"][0]["checkpoints"][0]["level"], "HIGH")

    @patch("trips.services.analysis.fetch_forecasts")
    @patch("trips.services.analysis.get_routes")
    def test_no_travel_route_loses_to_calm_route_even_if_longer(
        self,
        mock_get_routes: Mock,
        mock_fetch_forecasts: Mock,
    ) -> None:
        calm_route = _route("route-1", ((40.0, -75.0), (41.0, -74.0)), 140.0, 10000.0)
        windy_route = _route("route-2", ((40.0, -75.0), (40.3, -74.7), (41.0, -74.0)), 100.0, 7000.0)
        windy_checkpoints = _route_checkpoints(windy_route, self.departure, interval_miles=50)
        calm_checkpoints = _route_checkpoints(calm_route, self.departure, interval_miles=50)
        mock_get_routes.return_value = [windy_route, calm_route]
        mock_fetch_forecasts.return_value = [
            *[_forecast_for_eta(checkpoint.eta, 55.0) for checkpoint in windy_checkpoints],
            *[_forecast_for_eta(checkpoint.eta, 10.0) for checkpoint in calm_checkpoints],
        ]

        result = analyze_trip(self.origin, self.destination, self.departure, 10000.0, interval_miles=50)

        self.assertEqual(result["recommended_route_id"], "route-1")
        self.assertEqual(result["routes"][0]["route_id"], "route-1")
        self.assertEqual(result["routes"][1]["summary"]["worst_level"], "NO_TRAVEL")

    def test_downsample_geometry_keeps_first_and_last_and_short_list_unchanged(self) -> None:
        long_geometry = [(float(index), float(index)) for index in range(10000)]

        downsampled = downsample_geometry(long_geometry)
        short = [(1.0, 2.0), (3.0, 4.0)]

        self.assertEqual(len(downsampled), 500)
        self.assertEqual(downsampled[0], long_geometry[0])
        self.assertEqual(downsampled[-1], long_geometry[-1])
        self.assertEqual(downsample_geometry(short), short)

    @patch("trips.services.analysis.fetch_forecasts")
    @patch("trips.services.analysis.get_routes")
    def test_result_is_json_serialisable(self, mock_get_routes: Mock, mock_fetch_forecasts: Mock) -> None:
        route = _route("route-1", ((40.0, -75.0), (41.0, -74.0)), 100.0, 7200.0)
        mock_get_routes.return_value = [route]
        checkpoints = _route_checkpoints(route, self.departure)
        mock_fetch_forecasts.return_value = [_forecast_for_eta(checkpoint.eta, 10.0) for checkpoint in checkpoints]

        result = analyze_trip(self.origin, self.destination, self.departure, 1000.0)

        self.assertIsInstance(json.dumps(result), str)

    @patch("trips.services.analysis.fetch_forecasts")
    @patch("trips.services.analysis.get_routes")
    def test_explicit_interval_overrides_automatic_interval(
        self,
        mock_get_routes: Mock,
        mock_fetch_forecasts: Mock,
    ) -> None:
        route = _route("route-1", ((40.0, -75.0), (41.0, -74.0)), 100.0, 7200.0)
        mock_get_routes.return_value = [route]
        checkpoints = _route_checkpoints(route, self.departure, interval_miles=50)
        mock_fetch_forecasts.return_value = [_forecast_for_eta(checkpoint.eta, 10.0) for checkpoint in checkpoints]

        result = analyze_trip(self.origin, self.destination, self.departure, 1000.0, interval_miles=50)

        self.assertEqual(result["routes"][0]["interval_miles"], 50)

    @patch("trips.services.analysis.fetch_forecasts")
    @patch("trips.services.analysis.get_routes")
    def test_authoritative_route_distance_flows_through_analysis(
        self,
        mock_get_routes: Mock,
        mock_fetch_forecasts: Mock,
    ) -> None:
        route = _route(
            "route-1",
            ((40.0, -75.0), (40.5, -74.7), (41.0, -74.0)),
            150.0,
            7200.0,
        )
        checkpoints = _route_checkpoints(route, self.departure, interval_miles=50)
        mock_get_routes.return_value = [route]
        mock_fetch_forecasts.return_value = [_forecast_for_eta(checkpoint.eta, 10.0) for checkpoint in checkpoints]

        result = analyze_trip(self.origin, self.destination, self.departure, 1000.0, interval_miles=50)

        for serialized_route in result["routes"]:
            miles_by_level = serialized_route["summary"]["miles_by_level"]
            non_zero_levels = sum(1 for miles in miles_by_level.values() if miles > 0)
            self.assertLessEqual(
                abs(sum(miles_by_level.values()) - serialized_route["distance_miles"]),
                0.05 * non_zero_levels + 0.05,
            )
            self.assertAlmostEqual(
                serialized_route["checkpoints"][-1]["mile_marker"],
                serialized_route["distance_miles"],
                delta=1e-6,
            )