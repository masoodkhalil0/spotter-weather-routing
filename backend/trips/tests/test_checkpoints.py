from datetime import datetime, timedelta, timezone

from django.test import SimpleTestCase

from trips.services.checkpoints import (
    Checkpoint,
    choose_interval_miles,
    generate_checkpoints,
    haversine_miles,
    polyline_length_miles,
)


class PolylineLengthTests(SimpleTestCase):
    def test_haversine_sanity_for_one_degree_of_latitude(self) -> None:
        distance = haversine_miles((0.0, 0.0), (1.0, 0.0))

        self.assertAlmostEqual(distance, 69.0, delta=1.0)

    def test_polyline_length_matches_sum_of_segments(self) -> None:
        coordinates = [(0.0, 0.0), (0.5, 0.0), (1.0, 0.0)]

        direct = haversine_miles((0.0, 0.0), (0.5, 0.0)) + haversine_miles(
            (0.5, 0.0),
            (1.0, 0.0),
        )

        self.assertAlmostEqual(polyline_length_miles(coordinates), direct, places=6)


class ChooseIntervalTests(SimpleTestCase):
    def test_choose_interval_boundaries(self) -> None:
        self.assertEqual(choose_interval_miles(150.0), 10)
        self.assertEqual(choose_interval_miles(151.0), 25)
        self.assertEqual(choose_interval_miles(500.0), 25)
        self.assertEqual(choose_interval_miles(501.0), 50)


class GenerateCheckpointsTests(SimpleTestCase):
    def setUp(self) -> None:
        self.departure = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)

    def test_checkpoint_markers_for_straight_line_route(self) -> None:
        end_lat = 100.0 / 69.09409442795152
        coordinates = [(0.0, 0.0), (end_lat, 0.0)]
        total_miles = polyline_length_miles(coordinates)

        checkpoints = generate_checkpoints(
            coordinates=coordinates,
            duration_seconds=7200.0,
            departure=self.departure,
            interval_miles=25.0,
        )

        self.assertEqual(len(checkpoints), 5)
        expected_markers = [0.0, 25.0, 50.0, 75.0, total_miles]
        actual_markers = [checkpoint.mile_marker for checkpoint in checkpoints]

        for actual, expected in zip(actual_markers, expected_markers, strict=True):
            self.assertAlmostEqual(actual, expected, delta=1e-6)

        self.assertAlmostEqual(actual_markers[-1], 100.0, delta=0.1)

    def test_final_point_added_when_route_not_multiple_of_interval(self) -> None:
        end_lat = 90.0 / 69.0
        coordinates = [(0.0, 0.0), (end_lat, 0.0)]

        checkpoints = generate_checkpoints(
            coordinates=coordinates,
            duration_seconds=5400.0,
            departure=self.departure,
            interval_miles=25.0,
        )

        markers = [checkpoint.mile_marker for checkpoint in checkpoints]
        self.assertEqual(len(markers), 5)
        self.assertAlmostEqual(markers[0], 0.0, places=6)
        self.assertAlmostEqual(markers[1], 25.0, delta=0.5)
        self.assertAlmostEqual(markers[2], 50.0, delta=0.5)
        self.assertAlmostEqual(markers[3], 75.0, delta=0.5)
        self.assertGreater(markers[4], 75.0)
        self.assertLess(markers[4], 100.0)

    def test_eta_endpoints_and_monotonicity(self) -> None:
        end_lat = 100.0 / 69.09409442795152
        coordinates = [(0.0, 0.0), (end_lat, 0.0)]
        duration = 3600.0

        checkpoints = generate_checkpoints(
            coordinates=coordinates,
            duration_seconds=duration,
            departure=self.departure,
            interval_miles=25.0,
        )

        self.assertEqual(checkpoints[0].eta, self.departure)
        self.assertEqual(checkpoints[-1].eta, self.departure + timedelta(seconds=duration))

        for previous, current in zip(checkpoints, checkpoints[1:]):
            self.assertLessEqual(previous.eta, current.eta)

    def test_segment_miles_sum_to_total_length(self) -> None:
        coordinates = [(0.0, 0.0), (0.7, 0.0), (1.4, 0.0)]

        checkpoints = generate_checkpoints(
            coordinates=coordinates,
            duration_seconds=5000.0,
            departure=self.departure,
            interval_miles=30.0,
        )

        total_length = polyline_length_miles(coordinates)
        represented_length = sum(checkpoint.segment_miles for checkpoint in checkpoints)

        self.assertAlmostEqual(represented_length, total_length, delta=1e-6)

    def test_zero_length_route_returns_single_checkpoint(self) -> None:
        coordinates = [(10.0, 20.0), (10.0, 20.0)]

        checkpoints = generate_checkpoints(
            coordinates=coordinates,
            duration_seconds=100.0,
            departure=self.departure,
            interval_miles=10.0,
        )

        self.assertEqual(
            checkpoints,
            [
                Checkpoint(
                    index=0,
                    mile_marker=0.0,
                    lat=10.0,
                    lon=20.0,
                    eta=self.departure,
                    segment_miles=0.0,
                )
            ],
        )

    def test_invalid_inputs_raise_value_error(self) -> None:
        aware_departure = self.departure
        naive_departure = datetime(2026, 1, 1, 12, 0)
        valid_coordinates = [(0.0, 0.0), (1.0, 1.0)]

        with self.assertRaises(ValueError):
            polyline_length_miles([(0.0, 0.0)])

        with self.assertRaises(ValueError):
            polyline_length_miles([(91.0, 0.0), (0.0, 0.0)])

        with self.assertRaises(ValueError):
            polyline_length_miles([(0.0, 181.0), (0.0, 0.0)])

        with self.assertRaises(ValueError):
            generate_checkpoints(
                coordinates=[(0.0, 0.0)],
                duration_seconds=10.0,
                departure=aware_departure,
                interval_miles=5.0,
            )

        with self.assertRaises(ValueError):
            generate_checkpoints(
                coordinates=valid_coordinates,
                duration_seconds=-1.0,
                departure=aware_departure,
                interval_miles=5.0,
            )

        with self.assertRaises(ValueError):
            generate_checkpoints(
                coordinates=valid_coordinates,
                duration_seconds=10.0,
                departure=aware_departure,
                interval_miles=0.0,
            )

        with self.assertRaises(ValueError):
            generate_checkpoints(
                coordinates=valid_coordinates,
                duration_seconds=10.0,
                departure=naive_departure,
                interval_miles=5.0,
            )

        with self.assertRaises(ValueError):
            generate_checkpoints(
                coordinates=[(-91.0, 0.0), (0.0, 0.0)],
                duration_seconds=10.0,
                departure=aware_departure,
                interval_miles=5.0,
            )

        with self.assertRaises(ValueError):
            generate_checkpoints(
                coordinates=[(0.0, -181.0), (0.0, 0.0)],
                duration_seconds=10.0,
                departure=aware_departure,
                interval_miles=5.0,
            )