from __future__ import annotations

from unittest.mock import Mock, patch

from django.core.cache import cache
from django.test import SimpleTestCase
from requests.exceptions import Timeout

from trips.services.routing import (
    DISTINCT_OVERLAP_LIMIT,
    METERS_PER_MILE,
    TRUCK_SPEED_FACTOR,
    Route,
    RoutingServiceError,
    get_routes,
    offset_point,
    point_at_fraction,
    route_overlap,
)


def _response(payload: dict, status_code: int = 200) -> Mock:
    response = Mock()
    response.status_code = status_code
    response.json.return_value = payload
    return response


def _osrm_payload(
    coordinates: list[tuple[float, float]],
    distance_meters: float,
    duration_seconds: float,
    waypoint_distance_meters: float = 0.0,
    code: str = "Ok",
) -> dict:
    return {
        "code": code,
        "routes": [
            {
                "distance": distance_meters,
                "duration": duration_seconds,
                "geometry": {
                    "coordinates": [[lon, lat] for lat, lon in coordinates],
                },
            }
        ],
        "waypoints": [
            {"distance": 0.0, "location": [coordinates[0][1], coordinates[0][0]]},
            {"distance": waypoint_distance_meters, "location": [coordinates[-1][1], coordinates[-1][0]]},
            {"distance": 0.0, "location": [coordinates[-1][1], coordinates[-1][0]]},
        ][: max(2, min(3, len(coordinates)))],
    }


def _alternative_payload(routes: list[dict]) -> dict:
    return {
        "code": "Ok",
        "routes": routes,
        "waypoints": [
            {"distance": 0.0, "location": [-75.0, 40.0]},
            {"distance": 0.0, "location": [-74.0, 41.0]},
        ],
    }


class RoutingTests(SimpleTestCase):
    def setUp(self) -> None:
        cache.clear()
        self.origin = (40.0, -75.0)
        self.destination = (41.0, -74.0)

    @patch("trips.services.routing.sleep", return_value=None)
    @patch("trips.services.routing.requests.get")
    def test_conversion_meters_and_truck_speed_factor(self, mock_get: Mock, _: Mock) -> None:
        payload = _alternative_payload(
            [
                {
                    "distance": 16093.44,
                    "duration": 900.0,
                    "geometry": {"coordinates": [[-75.0, 40.0], [-74.0, 41.0]]},
                }
            ]
        )
        mock_get.return_value = _response(payload)

        routes = get_routes(self.origin, self.destination, count=1)

        self.assertEqual(routes[0].coordinates, ((40.0, -75.0), (41.0, -74.0)))
        self.assertAlmostEqual(routes[0].distance_miles, 10.0, places=6)
        self.assertAlmostEqual(routes[0].duration_seconds, 900.0 / TRUCK_SPEED_FACTOR, places=6)

    @patch("trips.services.routing.sleep", return_value=None)
    @patch("trips.services.routing.requests.get")
    def test_three_alternatives_returned_without_via_requests(self, mock_get: Mock, _: Mock) -> None:
        mock_get.return_value = _response(
            _alternative_payload(
                [
                    {
                        "distance": 10000.0,
                        "duration": 1000.0,
                        "geometry": {"coordinates": [[-75.0, 40.0], [-74.8, 40.2], [-74.0, 41.0]]},
                    },
                    {
                        "distance": 12000.0,
                        "duration": 1100.0,
                        "geometry": {"coordinates": [[-75.0, 40.0], [-75.2, 40.4], [-74.0, 41.0]]},
                    },
                    {
                        "distance": 13000.0,
                        "duration": 1200.0,
                        "geometry": {"coordinates": [[-75.0, 40.0], [-74.5, 40.8], [-74.0, 41.0]]},
                    },
                ]
            )
        )

        routes = get_routes(self.origin, self.destination, count=3)

        self.assertEqual(len(routes), 3)
        self.assertEqual(mock_get.call_count, 1)
        self.assertTrue(all(not route.is_generated for route in routes))

    @patch("trips.services.routing.sleep", return_value=None)
    @patch("trips.services.routing.requests.get")
    def test_via_request_adds_third_route_when_valid(self, mock_get: Mock, _: Mock) -> None:
        initial_payload = _alternative_payload(
            [
                {
                    "distance": 10000.0,
                    "duration": 1000.0,
                    "geometry": {"coordinates": [[-75.0, 40.0], [-74.9, 40.4], [-74.0, 41.0]]},
                },
                {
                    "distance": 11000.0,
                    "duration": 1050.0,
                    "geometry": {"coordinates": [[-75.0, 40.0], [-75.3, 40.4], [-74.0, 41.0]]},
                },
            ]
        )
        via_payload = _osrm_payload(
            [(40.0, -75.0), (41.2, -74.7), (41.0, -74.0)],
            distance_meters=12000.0,
            duration_seconds=1150.0,
            waypoint_distance_meters=100.0,
        )
        mock_get.side_effect = [_response(initial_payload), _response(via_payload)]

        routes = get_routes(self.origin, self.destination, count=3)

        self.assertEqual(len(routes), 3)
        self.assertEqual(mock_get.call_count, 2)
        self.assertTrue(routes[-1].is_generated)

    @patch("trips.services.routing.sleep", return_value=None)
    @patch("trips.services.routing.requests.get")
    def test_optional_via_failure_keeps_primary_routes(self, mock_get: Mock, _: Mock) -> None:
        initial_payload = _alternative_payload(
            [
                {
                    "distance": 10000.0,
                    "duration": 1000.0,
                    "geometry": {"coordinates": [[-75.0, 40.0], [-74.8, 40.2], [-74.0, 41.0]]},
                },
                {
                    "distance": 11000.0,
                    "duration": 1100.0,
                    "geometry": {"coordinates": [[-75.0, 40.0], [-74.6, 40.1], [-74.0, 41.0]]},
                },
            ]
        )
        mock_get.side_effect = [
            _response(initial_payload),
            _response({"code": "NoRoute", "routes": [], "waypoints": []}),
            _response({"code": "NoRoute", "routes": [], "waypoints": []}),
            _response({"code": "NoRoute", "routes": [], "waypoints": []}),
            _response({"code": "NoRoute", "routes": [], "waypoints": []}),
        ]

        with self.assertLogs("trips.services.routing", level="WARNING") as captured_logs:
            routes = get_routes(self.origin, self.destination, count=3)

        self.assertEqual(len(routes), 2)
        self.assertEqual([route.route_id for route in routes], ["route-1", "route-2"])
        self.assertTrue(any("Optional generated via route failed" in entry for entry in captured_logs.output))

    @patch("trips.services.routing.sleep", return_value=None)
    @patch("trips.services.routing.requests.get")
    def test_primary_request_failure_still_raises(self, mock_get: Mock, _: Mock) -> None:
        mock_get.return_value = _response({"code": "NoRoute", "routes": [], "waypoints": []})

        with self.assertRaisesMessage(RoutingServiceError, "No route found between these locations"):
            get_routes(self.origin, self.destination, count=3)

    @patch("trips.services.routing.sleep", return_value=None)
    @patch("trips.services.routing.requests.get")
    def test_second_via_side_can_succeed_after_first_side_fails(self, mock_get: Mock, _: Mock) -> None:
        initial_payload = _alternative_payload(
            [
                {
                    "distance": 10000.0,
                    "duration": 1000.0,
                    "geometry": {"coordinates": [[-75.0, 40.0], [-74.8, 40.2], [-74.0, 41.0]]},
                },
                {
                    "distance": 11000.0,
                    "duration": 1100.0,
                    "geometry": {"coordinates": [[-75.0, 40.0], [-74.6, 40.1], [-74.0, 41.0]]},
                },
            ]
        )
        via_payload = _osrm_payload(
            [(40.0, -75.0), (40.4, -75.4), (41.0, -74.0)],
            distance_meters=13000.0,
            duration_seconds=1200.0,
        )
        mock_get.side_effect = [
            _response(initial_payload),
            _response({"code": "NoRoute", "routes": [], "waypoints": []}),
            _response(via_payload),
        ]

        with self.assertLogs("trips.services.routing", level="WARNING") as captured_logs:
            routes = get_routes(self.origin, self.destination, count=3)

        self.assertEqual(len(routes), 3)
        self.assertTrue(routes[2].is_generated)
        self.assertTrue(any("Optional generated via route failed" in entry for entry in captured_logs.output))

    @patch("trips.services.routing.sleep", return_value=None)
    @patch("trips.services.routing.requests.get")
    def test_invalid_via_candidates_return_two_routes_without_error(self, mock_get: Mock, _: Mock) -> None:
        initial_payload = _alternative_payload(
            [
                {
                    "distance": 10000.0,
                    "duration": 1000.0,
                    "geometry": {"coordinates": [[-75.0, 40.0], [-74.9, 40.4], [-74.0, 41.0]]},
                },
                {
                    "distance": 11000.0,
                    "duration": 1050.0,
                    "geometry": {"coordinates": [[-75.0, 40.0], [-75.3, 40.4], [-74.0, 41.0]]},
                },
            ]
        )
        too_long = _osrm_payload(
            [(40.0, -75.0), (42.0, -73.5), (41.0, -74.0)],
            distance_meters=20000.0,
            duration_seconds=1500.0,
            waypoint_distance_meters=0.0,
        )
        too_far = _osrm_payload(
            [(40.0, -75.0), (41.3, -74.8), (41.0, -74.0)],
            distance_meters=12000.0,
            duration_seconds=1150.0,
            waypoint_distance_meters=METERS_PER_MILE * 11.0,
        )
        duplicate = _osrm_payload(
            [(40.0, -75.0), (40.2, -74.8), (41.0, -74.0)],
            distance_meters=11500.0,
            duration_seconds=1100.0,
            waypoint_distance_meters=0.0,
        )
        duplicate["routes"][0]["geometry"]["coordinates"] = initial_payload["routes"][0]["geometry"]["coordinates"]
        mock_get.side_effect = [
            _response(initial_payload),
            _response(too_long),
            _response(too_far),
            _response(duplicate),
            _response(duplicate),
        ]

        routes = get_routes(self.origin, self.destination, count=3)

        self.assertEqual(len(routes), 2)
        self.assertEqual(mock_get.call_count, 5)
        self.assertTrue(all(not route.is_generated for route in routes))

    @patch("trips.services.routing.sleep", return_value=None)
    @patch("trips.services.routing.requests.get")
    def test_request_cap_of_five_is_respected(self, mock_get: Mock, _: Mock) -> None:
        initial_payload = _alternative_payload(
            [
                {
                    "distance": 10000.0,
                    "duration": 1000.0,
                    "geometry": {"coordinates": [[-75.0, 40.0], [-74.9, 40.4], [-74.0, 41.0]]},
                }
            ]
        )
        duplicate = _osrm_payload(
            [(40.0, -75.0), (40.2, -74.8), (41.0, -74.0)],
            distance_meters=11000.0,
            duration_seconds=1100.0,
            waypoint_distance_meters=0.0,
        )
        duplicate["routes"][0]["geometry"]["coordinates"] = initial_payload["routes"][0]["geometry"]["coordinates"]
        mock_get.side_effect = [
            _response(initial_payload),
            _response(duplicate),
            _response(duplicate),
            _response(duplicate),
            _response(duplicate),
        ]

        routes = get_routes(self.origin, self.destination, count=3)

        self.assertEqual(len(routes), 1)
        self.assertEqual(mock_get.call_count, 5)

    @patch("trips.services.routing.sleep", return_value=None)
    @patch("trips.services.routing.requests.get")
    def test_identical_routes_are_deduplicated(self, mock_get: Mock, _: Mock) -> None:
        geometry = [[-75.0, 40.0], [-74.5, 40.5], [-74.0, 41.0]]
        mock_get.return_value = _response(
            _alternative_payload(
                [
                    {"distance": 10000.0, "duration": 1000.0, "geometry": {"coordinates": geometry}},
                    {"distance": 10050.0, "duration": 1005.0, "geometry": {"coordinates": geometry}},
                ]
            )
        )

        routes = get_routes(self.origin, self.destination, count=3)

        self.assertEqual(len(routes), 1)

    def test_route_overlap_identical_and_far_apart(self) -> None:
        route_a = Route(
            route_id="a",
            coordinates=((40.0, -75.0), (40.5, -74.5), (41.0, -74.0)),
            distance_miles=100.0,
            duration_seconds=1000.0,
            is_generated=False,
        )
        route_b = Route(
            route_id="b",
            coordinates=((40.0, -75.0), (40.5, -74.5), (41.0, -74.0)),
            distance_miles=100.0,
            duration_seconds=1200.0,
            is_generated=False,
        )
        route_c = Route(
            route_id="c",
            coordinates=((10.0, 10.0), (11.0, 11.0), (12.0, 12.0)),
            distance_miles=100.0,
            duration_seconds=1200.0,
            is_generated=False,
        )

        self.assertGreaterEqual(route_overlap(route_a, route_b), 0.99)
        self.assertLess(route_overlap(route_a, route_c), 0.01)

    def test_offset_point_and_point_at_fraction_sanity(self) -> None:
        north = offset_point(0.0, 0.0, 0.0, 69.0)
        midpoint = point_at_fraction(((0.0, 0.0), (10.0, 10.0)), 0.5)

        self.assertAlmostEqual(north[0], 1.0, delta=0.1)
        self.assertAlmostEqual(midpoint[0], 5.0, delta=0.1)
        self.assertAlmostEqual(midpoint[1], 5.0, delta=0.1)

    @patch("trips.services.routing.sleep", return_value=None)
    @patch("trips.services.routing.requests.get")
    def test_no_route_code_raises_clean_error(self, mock_get: Mock, _: Mock) -> None:
        mock_get.return_value = _response({"code": "NoRoute", "routes": [], "waypoints": []})

        with self.assertRaisesMessage(RoutingServiceError, "No route found between these locations"):
            get_routes(self.origin, self.destination)

    @patch("trips.services.routing.sleep", return_value=None)
    @patch("trips.services.routing.requests.get")
    def test_malformed_json_raises_clean_error(self, mock_get: Mock, _: Mock) -> None:
        response = Mock()
        response.status_code = 200
        response.json.side_effect = ValueError("bad json")
        mock_get.return_value = response

        with self.assertRaisesMessage(RoutingServiceError, "Routing service returned malformed data"):
            get_routes(self.origin, self.destination)

    @patch("trips.services.routing.sleep", return_value=None)
    @patch("trips.services.routing.requests.get")
    def test_500_then_success_retries(self, mock_get: Mock, _: Mock) -> None:
        success = _response(
            _alternative_payload(
                [
                    {
                        "distance": 10000.0,
                        "duration": 1000.0,
                        "geometry": {"coordinates": [[-75.0, 40.0], [-74.0, 41.0]]},
                    }
                ]
            )
        )
        mock_get.side_effect = [_response({}, status_code=500), success]

        routes = get_routes(self.origin, self.destination, count=1)

        self.assertEqual(len(routes), 1)
        self.assertEqual(mock_get.call_count, 2)

    @patch("trips.services.routing.sleep", return_value=None)
    @patch("trips.services.routing.requests.get")
    def test_double_failure_raises(self, mock_get: Mock, _: Mock) -> None:
        mock_get.side_effect = [Timeout(), Timeout()]

        with self.assertRaisesMessage(RoutingServiceError, "Routing service timed out"):
            get_routes(self.origin, self.destination, count=1)

        self.assertEqual(mock_get.call_count, 2)

    @patch("trips.services.routing.sleep", return_value=None)
    @patch("trips.services.routing.requests.get")
    def test_caching_skips_second_http_call(self, mock_get: Mock, _: Mock) -> None:
        mock_get.return_value = _response(
            _alternative_payload(
                [
                    {
                        "distance": 10000.0,
                        "duration": 1000.0,
                        "geometry": {"coordinates": [[-75.0, 40.0], [-74.0, 41.0]]},
                    }
                ]
            )
        )

        first = get_routes(self.origin, self.destination, count=1)
        second = get_routes(self.origin, self.destination, count=1)

        self.assertEqual(first, second)
        self.assertEqual(mock_get.call_count, 1)

    def test_overlap_limit_constant_is_reasonable(self) -> None:
        self.assertGreater(DISTINCT_OVERLAP_LIMIT, 0.5)