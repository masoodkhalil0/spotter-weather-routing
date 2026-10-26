from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone as django_timezone
from rest_framework.test import APITestCase

from trips.services.geocoding import GeocodingError, Place
from trips.services.routing import RoutingServiceError
from trips.services.weather import WeatherServiceError


class ApiTests(APITestCase):
    def setUp(self) -> None:
        cache.clear()
        self.health_url = reverse("api-health")
        self.geocode_url = reverse("api-geocode")
        self.analyze_url = reverse("api-analyze")
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

    @patch("trips.api.views.analyze_trip")
    def test_analyze_valid_request_returns_200_and_calls_service(self, mock_analyze_trip) -> None:
        mock_analyze_trip.return_value = {"recommended_route_id": "route-1", "routes": []}

        response = self.client.post(self.analyze_url, data=self._payload(), format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"recommended_route_id": "route-1", "routes": []})
        mock_analyze_trip.assert_called_once()
        origin, destination, departure, load_weight_lb, interval_miles = mock_analyze_trip.call_args.args
        self.assertEqual(origin, (40.0, -75.0))
        self.assertEqual(destination, (41.0, -74.0))
        self.assertEqual(departure.tzinfo, timezone.utc)
        self.assertEqual(load_weight_lb, 12000.0)
        self.assertEqual(interval_miles, 25)

    def test_analyze_validation_errors_return_400(self) -> None:
        cases = [
            self._payload(origin={"lat": 95.0, "lon": -75.0}),
            self._payload(destination={"lat": 41.0, "lon": -181.0}),
            self._payload(destination={"lat": 40.0, "lon": -75.0}),
            self._payload(departure=(django_timezone.now() - timedelta(hours=2)).replace(microsecond=0).isoformat()),
            self._payload(departure=(django_timezone.now() + timedelta(days=11)).replace(microsecond=0).isoformat()),
            self._payload(load_weight_lb=-1),
            self._payload(load_weight_lb=80001),
            self._payload(interval_miles=15),
        ]

        for payload in cases:
            with self.subTest(payload=payload):
                response = self.client.post(self.analyze_url, data=payload, format="json")
                self.assertEqual(response.status_code, 400)

    @patch("trips.api.views.analyze_trip")
    def test_naive_departure_is_accepted_and_treated_as_utc(self, mock_analyze_trip) -> None:
        mock_analyze_trip.return_value = {"recommended_route_id": "route-1", "routes": []}
        naive_departure = datetime.utcnow().replace(microsecond=0) + timedelta(hours=2)

        response = self.client.post(
            self.analyze_url,
            data=self._payload(departure=naive_departure.isoformat()),
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        departure = mock_analyze_trip.call_args.args[2]
        self.assertEqual(departure.tzinfo, timezone.utc)

    @patch("trips.api.views.analyze_trip")
    def test_routing_service_error_returns_502_without_raw_exception_text(self, mock_analyze_trip) -> None:
        mock_analyze_trip.side_effect = RoutingServiceError("osrm exploded")

        with self.assertLogs("trips", level="WARNING") as captured_logs:
            response = self.client.post(self.analyze_url, data=self._payload(), format="json")

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json(), {"detail": "Routing upstream failed."})
        self.assertNotIn("osrm exploded", response.content.decode())
        self.assertTrue(any("Routing upstream failed: osrm exploded" in entry for entry in captured_logs.output))

    @patch("trips.api.views.analyze_trip")
    def test_weather_service_error_returns_502_without_raw_exception_text(self, mock_analyze_trip) -> None:
        mock_analyze_trip.side_effect = WeatherServiceError("meteo exploded")

        with self.assertLogs("trips", level="WARNING") as captured_logs:
            response = self.client.post(self.analyze_url, data=self._payload(), format="json")

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json(), {"detail": "Weather upstream failed."})
        self.assertNotIn("meteo exploded", response.content.decode())
        self.assertTrue(any("Weather upstream failed: meteo exploded" in entry for entry in captured_logs.output))

    @patch("trips.api.views.analyze_trip")
    def test_unexpected_exception_returns_500_with_generic_message(self, mock_analyze_trip) -> None:
        mock_analyze_trip.side_effect = RuntimeError("trace me")

        response = self.client.post(self.analyze_url, data=self._payload(), format="json")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json(), {"detail": "Internal server error."})
        self.assertNotIn("trace me", response.content.decode())
        self.assertNotIn("Traceback", response.content.decode())

    @patch("trips.api.views.analyze_trip")
    def test_analyze_throttling_returns_429_on_eleventh_request(self, mock_analyze_trip) -> None:
        mock_analyze_trip.return_value = {"recommended_route_id": "route-1", "routes": []}

        for _ in range(10):
            response = self.client.post(self.analyze_url, data=self._payload(), format="json")
            self.assertEqual(response.status_code, 200)

        response = self.client.post(self.analyze_url, data=self._payload(), format="json")

        self.assertEqual(response.status_code, 429)

    def test_non_json_content_type_is_rejected(self) -> None:
        response = self.client.post(self.analyze_url, data="origin=1", content_type="application/x-www-form-urlencoded")

        self.assertEqual(response.status_code, 415)