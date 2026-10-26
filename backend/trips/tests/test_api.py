from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone as django_timezone
from rest_framework.test import APITestCase

from trips.services.geocoding import GeocodingError, Place
from trips.services.routing import NoRouteFoundError, RoutingServiceError
from trips.services.timezones import TimezoneLookupError
from trips.services.weather import WeatherServiceError


class ApiTests(APITestCase):
    def setUp(self) -> None:
        cache.clear()
        self.health_url = reverse("api-health")
        self.geocode_url = reverse("api-geocode")
        self.timezone_url = reverse("api-timezone")
        self.analyze_url = reverse("api-analyze")
        self.heatmap_url = reverse("api-heatmap")
        self.departure = (django_timezone.now() + timedelta(hours=2)).replace(microsecond=0)

    def _payload(self, **overrides):
        payload = {
            "origin": {"lat": 40.0, "lon": -75.0},
            "destination": {"lat": 41.0, "lon": -74.0},
            "departure": self.departure.isoformat(),
            "load_weight_lb": 12000.0,
            "interval_miles": 25,
        }
        payload.update(overrides)
        return payload

    def test_health_returns_200(self) -> None:
        response = self.client.get(self.health_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_geocode_missing_and_short_q_return_400(self) -> None:
        missing_response = self.client.get(self.geocode_url)
        short_response = self.client.get(self.geocode_url, {"q": " a "})

        self.assertEqual(missing_response.status_code, 400)
        self.assertEqual(short_response.status_code, 400)

    @patch("trips.api.views.search_places")
    def test_geocode_success_shape(self, mock_search_places) -> None:
        mock_search_places.return_value = [Place(label="Philadelphia, PA", lat=39.95, lon=-75.16)]

        response = self.client.get(self.geocode_url, {"q": "  Philadelphia  "})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"results": [{"label": "Philadelphia, PA", "lat": 39.95, "lon": -75.16}]},
        )
        mock_search_places.assert_called_once_with("Philadelphia")

    @patch("trips.api.views.search_places")
    def test_geocode_error_returns_502(self, mock_search_places) -> None:
        mock_search_places.side_effect = GeocodingError("boom")

        with self.assertLogs("trips", level="WARNING") as captured_logs:
            response = self.client.get(self.geocode_url, {"q": "Denver"})

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json(), {"detail": "Geocoding upstream failed."})
        self.assertNotIn("boom", response.content.decode())
        self.assertTrue(any("Geocoding upstream failed: boom" in entry for entry in captured_logs.output))

    @patch("trips.api.views.lookup_timezone")
    def test_timezone_endpoint_returns_expected_shape_and_caches(self, mock_lookup_timezone) -> None:
        mock_lookup_timezone.return_value = {"timezone": "America/Chicago", "utc_offset_minutes": -300}

        first = self.client.get(self.timezone_url, {"lat": 41.88, "lon": -87.63})
        second = self.client.get(self.timezone_url, {"lat": 41.88, "lon": -87.63})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json(), {"timezone": "America/Chicago", "utc_offset_minutes": -300})
        self.assertEqual(second.status_code, 200)

    def test_timezone_endpoint_bad_lat_lon_return_400(self) -> None:
        bad_number = self.client.get(self.timezone_url, {"lat": "north", "lon": -75.0})
        out_of_range = self.client.get(self.timezone_url, {"lat": 91, "lon": -181})

        self.assertEqual(bad_number.status_code, 400)
        self.assertEqual(out_of_range.status_code, 400)

    @patch("trips.api.views.lookup_timezone")
    def test_timezone_endpoint_upstream_failure_returns_502(self, mock_lookup_timezone) -> None:
        mock_lookup_timezone.side_effect = TimezoneLookupError("Timezone upstream failed.")

        with self.assertLogs("trips", level="WARNING") as captured_logs:
            response = self.client.get(self.timezone_url, {"lat": 40.0, "lon": -75.0})

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json(), {"detail": "Timezone upstream failed."})
        self.assertTrue(any("Timezone upstream failed: Timezone upstream failed." in entry for entry in captured_logs.output))

    @patch("trips.api.views.lookup_timezone")
    @patch("trips.api.views.analyze_trip")
    def test_analyze_valid_request_returns_200_and_calls_service(self, mock_analyze_trip, mock_lookup_timezone) -> None:
        mock_lookup_timezone.return_value = {"timezone": "America/New_York", "utc_offset_minutes": -240}
        mock_analyze_trip.return_value = {
            "recommended_route_id": "route-1",
            "origin_timezone": "America/New_York",
            "routes": [],
        }

        response = self.client.post(self.analyze_url, data=self._payload(), format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"recommended_route_id": "route-1", "origin_timezone": "America/New_York", "routes": []},
        )
        mock_analyze_trip.assert_called_once()
        origin, destination, departure, load_weight_lb, interval_miles = mock_analyze_trip.call_args.args
        self.assertEqual(origin, (40.0, -75.0))
        self.assertEqual(destination, (41.0, -74.0))
        self.assertEqual(departure.tzinfo, timezone.utc)
        self.assertEqual(load_weight_lb, 12000.0)
        self.assertEqual(interval_miles, 25)
        self.assertEqual(mock_analyze_trip.call_args.kwargs["origin_timezone"], "America/New_York")

    @patch("trips.api.views.lookup_timezone")
    @patch("trips.api.views.analyze_trip")
    def test_naive_departure_chicago_uses_zoneinfo(self, mock_analyze_trip, mock_lookup_timezone) -> None:
        mock_lookup_timezone.return_value = {"timezone": "America/Chicago", "utc_offset_minutes": -300}
        mock_analyze_trip.return_value = {"routes": [], "recommended_route_id": None, "origin_timezone": "America/Chicago"}
        naive_departure = (django_timezone.now().astimezone(ZoneInfo("America/Chicago")) + timedelta(hours=2)).replace(microsecond=0, tzinfo=None)

        response = self.client.post(
            self.analyze_url,
            data=self._payload(origin={"lat": 41.88, "lon": -87.63}, departure=naive_departure.isoformat()),
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        called_departure = mock_analyze_trip.call_args.args[2]
        expected_departure = naive_departure.replace(tzinfo=ZoneInfo("America/Chicago")).astimezone(timezone.utc)
        self.assertEqual(called_departure, expected_departure, response.content)
        self.assertEqual(mock_analyze_trip.call_args.kwargs["origin_timezone"], "America/Chicago", response.content)

    @patch("trips.api.views.lookup_timezone")
    def test_naive_departure_karachi_uses_zoneinfo(self, mock_lookup_timezone) -> None:
        mock_lookup_timezone.return_value = {"timezone": "Asia/Karachi", "utc_offset_minutes": 300}
        departure = (django_timezone.now().astimezone(ZoneInfo("Asia/Karachi")) + timedelta(hours=2)).replace(microsecond=0, tzinfo=None)

        with patch("trips.api.views.analyze_trip", return_value={"recommended_route_id": "route-1", "origin_timezone": "Asia/Karachi", "routes": []}) as mock_analyze_trip:
            response = self.client.post(
                self.analyze_url,
                data=self._payload(departure=departure.isoformat()),
                format="json",
            )

        self.assertEqual(response.status_code, 200, response.content)
        resolved_departure = mock_analyze_trip.call_args.args[2]
        expected = departure.replace(tzinfo=ZoneInfo("Asia/Karachi")).astimezone(timezone.utc)
        self.assertEqual(resolved_departure, expected, response.content)

    @patch("trips.api.views.lookup_timezone")
    def test_analyze_validation_errors_return_400(self, mock_lookup_timezone) -> None:
        mock_lookup_timezone.return_value = {"timezone": "America/Chicago", "utc_offset_minutes": -300}
        cases = [
            ("invalid departure format", self._payload(departure="not-a-date"), "departure"),
            ("invalid origin latitude", self._payload(origin={"lat": 999.0, "lon": -75.0}), "origin"),
            ("invalid destination longitude", self._payload(destination={"lat": 40.0, "lon": -200.0}), "destination"),
            ("negative weight", self._payload(load_weight_lb=-1.0), "load_weight_lb"),
            ("weight above maximum", self._payload(load_weight_lb=80001), "load_weight_lb"),
            ("invalid interval", self._payload(interval_miles=15), "interval_miles"),
            (
                "identical origin destination",
                self._payload(origin={"lat": 40.0, "lon": -75.0}, destination={"lat": 40.0, "lon": -75.0}),
                "non_field_errors",
            ),
            (
                "aware departure 2 hours in the past",
                self._payload(departure=(django_timezone.now() - timedelta(hours=2)).replace(microsecond=0, tzinfo=timezone.utc).isoformat()),
                "departure",
            ),
            (
                "aware departure 11 days ahead",
                self._payload(departure=(django_timezone.now() + timedelta(days=11)).replace(microsecond=0, tzinfo=timezone.utc).isoformat()),
                "departure",
            ),
        ]

        for label, payload, expected_key in cases:
            with self.subTest(case=label):
                cache.clear()
                response = self.client.post(self.analyze_url, data=payload, format="json")
                self.assertEqual(response.status_code, 400)
                self.assertIn(expected_key, response.json())
    @patch("trips.api.views.lookup_timezone")
    def test_departure_window_is_checked_after_conversion(self, mock_lookup_timezone) -> None:
        mock_lookup_timezone.return_value = {"timezone": "Pacific/Kiritimati", "utc_offset_minutes": 840}
        too_old = (django_timezone.now().astimezone(timezone.utc) + timedelta(hours=2)).replace(tzinfo=None, microsecond=0)

        response = self.client.post(
            self.analyze_url,
            data=self._payload(origin={"lat": 1.87, "lon": -157.43}, departure=too_old.isoformat()),
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"departure": ["Departure must be within the last hour or later."]})

    @patch("trips.api.views.lookup_timezone")
    @patch("trips.api.views.analyze_trip")
    def test_naive_departure_lookup_failure_returns_502(self, mock_analyze_trip, mock_lookup_timezone) -> None:
        mock_lookup_timezone.side_effect = TimezoneLookupError("Timezone upstream failed.")
        departure = (django_timezone.now() + timedelta(hours=2)).replace(microsecond=0, tzinfo=None)

        with self.assertLogs("trips", level="WARNING") as captured_logs:
            response = self.client.post(
                self.analyze_url,
                data=self._payload(departure=departure.isoformat()),
                format="json",
            )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json(), {"detail": "Timezone upstream failed."})
        mock_analyze_trip.assert_not_called()
        self.assertTrue(any("Timezone upstream failed: Timezone upstream failed." in entry for entry in captured_logs.output))

    @patch("trips.api.views.lookup_timezone")
    @patch("trips.api.views.analyze_trip")
    def test_aware_departure_lookup_failure_still_succeeds_with_null_origin_timezone(self, mock_analyze_trip, mock_lookup_timezone) -> None:
        mock_lookup_timezone.side_effect = TimezoneLookupError("Timezone upstream failed.")
        mock_analyze_trip.return_value = {"recommended_route_id": "route-1", "origin_timezone": None, "routes": []}
        aware_departure = (django_timezone.now() + timedelta(hours=2)).replace(microsecond=0, tzinfo=timezone.utc)

        response = self.client.post(
            self.analyze_url,
            data=self._payload(departure=aware_departure.isoformat()),
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["origin_timezone"], None)
        self.assertEqual(mock_analyze_trip.call_args.kwargs["origin_timezone"], None)

    @patch("trips.api.views.lookup_timezone")
    @patch("trips.api.views.analyze_trip")
    def test_routing_service_error_returns_502_without_raw_exception_text(self, mock_analyze_trip, mock_lookup_timezone) -> None:
        mock_lookup_timezone.return_value = {"timezone": "America/New_York", "utc_offset_minutes": -240}
        mock_analyze_trip.side_effect = RoutingServiceError("raw routing detail")

        with self.assertLogs("trips", level="WARNING") as captured_logs:
            response = self.client.post(self.analyze_url, data=self._payload(), format="json")

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json(), {"detail": "Routing upstream failed."})
        self.assertNotIn("raw routing detail", response.content.decode())
        self.assertTrue(any("Routing upstream failed: raw routing detail" in entry for entry in captured_logs.output))

    @patch("trips.api.views.lookup_timezone")
    @patch("trips.api.views.analyze_trip")
    def test_analyze_no_route_found_error_returns_400_detail(self, mock_analyze_trip, mock_lookup_timezone) -> None:
        mock_lookup_timezone.return_value = {"timezone": "America/New_York", "utc_offset_minutes": -240}
        mock_analyze_trip.side_effect = NoRouteFoundError("No drivable route found between these places.")

        response = self.client.post(self.analyze_url, data=self._payload(), format="json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"detail": "No drivable route found between these places."})

    @patch("trips.api.views.lookup_timezone")
    @patch("trips.api.views.analyze_trip")
    def test_value_error_returns_400_detail(self, mock_analyze_trip, mock_lookup_timezone) -> None:
        mock_lookup_timezone.return_value = {"timezone": "America/New_York", "utc_offset_minutes": -240}
        mock_analyze_trip.side_effect = ValueError("bad route")

        response = self.client.post(self.analyze_url, data=self._payload(), format="json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"detail": "bad route"})

    @patch("trips.api.views.lookup_timezone")
    @patch("trips.api.views.analyze_trip")
    def test_unexpected_exception_returns_500_with_generic_message(self, mock_analyze_trip, mock_lookup_timezone) -> None:
        mock_lookup_timezone.return_value = {"timezone": "America/New_York", "utc_offset_minutes": -240}
        mock_analyze_trip.side_effect = RuntimeError("trace me")

        with self.assertLogs("trips", level="ERROR"):
            response = self.client.post(self.analyze_url, data=self._payload(), format="json")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json(), {"detail": "Internal server error."})
        self.assertNotIn("trace me", response.content.decode())

    @patch("trips.api.views.lookup_timezone")
    @patch("trips.api.views.analyze_trip")
    def test_weather_service_error_returns_502_without_raw_exception_text(self, mock_analyze_trip, mock_lookup_timezone) -> None:
        mock_lookup_timezone.return_value = {"timezone": "America/New_York", "utc_offset_minutes": -240}
        mock_analyze_trip.side_effect = WeatherServiceError("meteo exploded")

        with self.assertLogs("trips", level="WARNING") as captured_logs:
            response = self.client.post(self.analyze_url, data=self._payload(), format="json")

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json(), {"detail": "Weather upstream failed."})
        self.assertNotIn("meteo exploded", response.content.decode())
        self.assertTrue(any("Weather upstream failed: meteo exploded" in entry for entry in captured_logs.output))

    @patch("trips.api.views.lookup_timezone")
    @patch("trips.api.views.analyze_trip")
    def test_analyze_throttling_returns_429_on_eleventh_request(self, mock_analyze_trip, mock_lookup_timezone) -> None:
        mock_lookup_timezone.return_value = {"timezone": "America/New_York", "utc_offset_minutes": -240}
        mock_analyze_trip.return_value = {"recommended_route_id": "route-1", "origin_timezone": None, "routes": []}

        for _ in range(10):
            response = self.client.post(self.analyze_url, data=self._payload(), format="json")
            self.assertEqual(response.status_code, 200)

        response = self.client.post(self.analyze_url, data=self._payload(), format="json")

        self.assertEqual(response.status_code, 429)

    def test_non_json_content_type_is_rejected(self) -> None:
        response = self.client.post(self.analyze_url, data="origin=1", content_type="application/x-www-form-urlencoded")

        self.assertEqual(response.status_code, 415)

    @patch("trips.api.views.lookup_timezone")
    @patch("trips.api.views.build_heatmap")
    @patch("trips.api.views.get_routes")
    def test_heatmap_valid_request_returns_200_and_calls_services(self, mock_get_routes, mock_build_heatmap, mock_lookup_timezone) -> None:
        mock_lookup_timezone.return_value = {"timezone": "America/New_York", "utc_offset_minutes": -240}
        mock_get_routes.return_value = [object()]
        mock_build_heatmap.return_value = {
            "hours": 24,
            "origin_timezone": "America/New_York",
            "level_names": ["LOW"],
            "points": [],
        }

        response = self.client.post(self.heatmap_url, data=self._payload(hours=24, interval_miles=None), format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"hours": 24, "origin_timezone": "America/New_York", "level_names": ["LOW"], "points": []},
        )
        mock_get_routes.assert_called_once()
        mock_build_heatmap.assert_called_once()
        self.assertEqual(mock_build_heatmap.call_args.kwargs["origin_timezone"], "America/New_York")

    def test_heatmap_invalid_request_returns_400(self) -> None:
        response = self.client.post(self.heatmap_url, data=self._payload(hours=49, interval_miles=None), format="json")

        self.assertEqual(response.status_code, 400)

    @patch("trips.api.views.get_routes")
    def test_heatmap_routing_service_error_returns_502_without_raw_exception_text(self, mock_get_routes) -> None:
        mock_get_routes.side_effect = RoutingServiceError("osrm exploded")

        with self.assertLogs("trips", level="WARNING") as captured_logs:
            response = self.client.post(self.heatmap_url, data=self._payload(interval_miles=None), format="json")

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json(), {"detail": "Routing upstream failed."})
        self.assertNotIn("osrm exploded", response.content.decode())
        self.assertTrue(any("Routing upstream failed: osrm exploded" in entry for entry in captured_logs.output))

    @patch("trips.api.views.get_routes")
    def test_heatmap_no_route_found_error_returns_400_detail(self, mock_get_routes) -> None:
        mock_get_routes.side_effect = NoRouteFoundError("No drivable road found near the destination.")

        response = self.client.post(self.heatmap_url, data=self._payload(interval_miles=None), format="json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"detail": "No drivable road found near the destination."})

    @patch("trips.api.views.lookup_timezone")
    @patch("trips.api.views.build_heatmap")
    @patch("trips.api.views.get_routes")
    def test_heatmap_weather_service_error_returns_502_without_raw_exception_text(self, mock_get_routes, mock_build_heatmap, mock_lookup_timezone) -> None:
        mock_lookup_timezone.return_value = {"timezone": "America/New_York", "utc_offset_minutes": -240}
        mock_get_routes.return_value = [object()]
        mock_build_heatmap.side_effect = WeatherServiceError("meteo exploded")

        with self.assertLogs("trips", level="WARNING") as captured_logs:
            response = self.client.post(self.heatmap_url, data=self._payload(interval_miles=None), format="json")

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json(), {"detail": "Weather upstream failed."})
        self.assertNotIn("meteo exploded", response.content.decode())
        self.assertTrue(any("Weather upstream failed: meteo exploded" in entry for entry in captured_logs.output))

    @patch("trips.api.views.lookup_timezone")
    @patch("trips.api.views.build_heatmap")
    @patch("trips.api.views.get_routes")
    def test_heatmap_aware_departure_lookup_failure_still_succeeds_with_null_origin_timezone(self, mock_get_routes, mock_build_heatmap, mock_lookup_timezone) -> None:
        mock_lookup_timezone.side_effect = TimezoneLookupError("Timezone upstream failed.")
        mock_get_routes.return_value = [object()]
        mock_build_heatmap.return_value = {"hours": 24, "origin_timezone": None, "level_names": ["LOW"], "points": []}
        aware_departure = (django_timezone.now() + timedelta(hours=2)).replace(microsecond=0, tzinfo=timezone.utc)

        response = self.client.post(
            self.heatmap_url,
            data=self._payload(departure=aware_departure.isoformat(), hours=24, interval_miles=None),
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["origin_timezone"], None)

    @patch("trips.api.views.lookup_timezone")
    @patch("trips.api.views.build_heatmap")
    def test_heatmap_naive_departure_lookup_failure_returns_502(self, mock_build_heatmap, mock_lookup_timezone) -> None:
        mock_lookup_timezone.side_effect = TimezoneLookupError("Timezone upstream failed.")
        departure = (django_timezone.now() + timedelta(hours=2)).replace(microsecond=0, tzinfo=None)

        with self.assertLogs("trips", level="WARNING") as captured_logs:
            response = self.client.post(
                self.heatmap_url,
                data=self._payload(departure=departure.isoformat(), interval_miles=None),
                format="json",
            )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json(), {"detail": "Timezone upstream failed."})
        mock_build_heatmap.assert_not_called()
        self.assertTrue(any("Timezone upstream failed: Timezone upstream failed." in entry for entry in captured_logs.output))

    @patch("trips.api.views.lookup_timezone")
    @patch("trips.api.views.build_heatmap")
    @patch("trips.api.views.get_routes")
    def test_heatmap_throttling_returns_429_on_eleventh_request(self, mock_get_routes, mock_build_heatmap, mock_lookup_timezone) -> None:
        mock_lookup_timezone.return_value = {"timezone": "America/New_York", "utc_offset_minutes": -240}
        mock_get_routes.return_value = [object()]
        mock_build_heatmap.return_value = {"hours": 24, "origin_timezone": None, "level_names": ["LOW"], "points": []}

        for _ in range(10):
            response = self.client.post(self.heatmap_url, data=self._payload(interval_miles=None), format="json")
            self.assertEqual(response.status_code, 200)

        response = self.client.post(self.heatmap_url, data=self._payload(interval_miles=None), format="json")

        self.assertEqual(response.status_code, 429)

