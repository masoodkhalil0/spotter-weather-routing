from __future__ import annotations

from unittest.mock import Mock, patch

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings
from requests.exceptions import Timeout

from trips.services.geocoding import GeocodingError, Place, search_places


def _response(payload: object, status_code: int = 200) -> Mock:
    response = Mock()
    response.status_code = status_code
    response.json.return_value = payload
    return response


@override_settings(OUTBOUND_USER_AGENT="WeatherRouteApp/1.0 (tests@example.com)")
class GeocodingTests(SimpleTestCase):
    def setUp(self) -> None:
        cache.clear()

    @patch("trips.services.geocoding.time.sleep", return_value=None)
    @patch("trips.services.geocoding.requests.get")
    def test_successful_search_returns_place_objects(self, mock_get: Mock, _: Mock) -> None:
        mock_get.return_value = _response(
            [
                {
                    "display_name": "Chicago, Illinois, United States",
                    "lat": "41.8781",
                    "lon": "-87.6298",
                }
            ]
        )

        places = search_places("Chicago")

        self.assertEqual(
            places,
            [Place(label="Chicago, Illinois, United States", lat=41.8781, lon=-87.6298)],
        )
        self.assertIsInstance(places[0].lat, float)
        self.assertIsInstance(places[0].lon, float)

    def test_query_normalization_and_validation(self) -> None:
        with patch("trips.services.geocoding.time.sleep", return_value=None), patch(
            "trips.services.geocoding.requests.get",
            return_value=_response([]),
        ) as mock_get:
            search_places("   New    York   ")

        self.assertEqual(mock_get.call_args.kwargs["params"]["q"], "New York")

        with self.assertRaises(ValueError):
            search_places("ab")

        with self.assertRaises(ValueError):
            search_places("x" * 201)

        with self.assertRaises(ValueError):
            search_places("Boston", limit=0)

        with self.assertRaises(ValueError):
            search_places("Boston", limit=11)

    @patch("trips.services.geocoding.time.sleep", return_value=None)
    @patch("trips.services.geocoding.requests.get")
    def test_cache_hit_avoids_http_and_normalized_query_key_is_reused(
        self,
        mock_get: Mock,
        _: Mock,
    ) -> None:
        mock_get.return_value = _response(
            [{"display_name": "Denver, Colorado, United States", "lat": "39.7392", "lon": "-104.9903"}]
        )

        first = search_places("Denver", limit=3)
        second = search_places("Denver", limit=3)
        third = search_places("  dEnVeR   ", limit=3)

        self.assertEqual(first, second)
        self.assertEqual(second, third)
        self.assertEqual(mock_get.call_count, 1)

    @patch("trips.services.geocoding.time.sleep", return_value=None)
    @patch("trips.services.geocoding.requests.get")
    def test_user_agent_and_country_code_are_sent(self, mock_get: Mock, _: Mock) -> None:
        mock_get.return_value = _response([])

        search_places("Seattle", limit=4)

        self.assertEqual(
            mock_get.call_args.kwargs["headers"]["User-Agent"],
            "WeatherRouteApp/1.0 (tests@example.com)",
        )
        self.assertEqual(mock_get.call_args.kwargs["params"]["countrycodes"], "us")

    @patch("trips.services.geocoding.time.sleep", return_value=None)
    @patch("trips.services.geocoding.requests.get")
    def test_retry_once_on_500_then_success(self, mock_get: Mock, mock_sleep: Mock) -> None:
        mock_get.side_effect = [_response([], status_code=500), _response([])]

        places = search_places("Austin")

        self.assertEqual(places, [])
        self.assertEqual(mock_get.call_count, 2)
        mock_sleep.assert_called()

    @patch("trips.services.geocoding.time.sleep", return_value=None)
    @patch("trips.services.geocoding.requests.get")
    def test_two_failures_raise_geocoding_error(self, mock_get: Mock, _: Mock) -> None:
        mock_get.side_effect = [Timeout(), Timeout()]

        with self.assertRaisesMessage(GeocodingError, "Geocoding service timed out"):
            search_places("Phoenix")

        self.assertEqual(mock_get.call_count, 2)

    @patch("trips.services.geocoding.time.sleep", return_value=None)
    @patch("trips.services.geocoding.requests.get")
    def test_malformed_json_and_invalid_items(self, mock_get: Mock, _: Mock) -> None:
        mock_get.return_value = _response({"not": "a list"})

        with self.assertRaisesMessage(GeocodingError, "Geocoding service returned malformed data"):
            search_places("Miami")

        cache.clear()
        mock_get.return_value = _response(
            [
                {"display_name": "Valid", "lat": "25.7617", "lon": "-80.1918"},
                {"display_name": "Bad Latitude", "lat": "north", "lon": "-80.0"},
                {"display_name": "Out of Range", "lat": "95.0", "lon": "-80.0"},
                {"display_name": 123, "lat": "25.0", "lon": "-80.0"},
            ]
        )

        places = search_places("Miami")

        self.assertEqual(places, [Place(label="Valid", lat=25.7617, lon=-80.1918)])

    @patch("trips.services.geocoding.time.sleep", return_value=None)
    @patch("trips.services.geocoding.requests.get")
    def test_empty_result_list_returns_empty_list(self, mock_get: Mock, _: Mock) -> None:
        mock_get.return_value = _response([])

        places = search_places("Nowhere")

        self.assertEqual(places, [])