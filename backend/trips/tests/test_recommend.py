from __future__ import annotations

from datetime import datetime, timezone

from django.test import SimpleTestCase

from trips.services.checkpoints import Checkpoint
from trips.services.recommend import explain_recommendation, rank_routes, summarize_route
from trips.services.risk import RiskAssessment, RiskLevel


def _checkpoint(index: int, segment_miles: float) -> Checkpoint:
    return Checkpoint(
        index=index,
        mile_marker=float(index) * 10.0,
        lat=0.0,
        lon=0.0,
        eta=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
        segment_miles=segment_miles,
    )


def _assessment(level: RiskLevel) -> RiskAssessment:
    return RiskAssessment(
        level=level,
        wind=level,
        rain=RiskLevel.LOW,
        snow=RiskLevel.LOW,
        reasons=(),
    )


class RecommendTests(SimpleTestCase):
    def test_miles_by_level_sums_and_includes_all_keys(self) -> None:
        checkpoints = [_checkpoint(0, 5.0), _checkpoint(1, 7.5), _checkpoint(2, 0.0)]
        assessments = [
            _assessment(RiskLevel.LOW),
            _assessment(RiskLevel.SEVERE),
            _assessment(RiskLevel.NO_TRAVEL),
        ]

        summary = summarize_route("route-1", 12.5, 1000.0, checkpoints, assessments)

        self.assertEqual(set(summary.miles_by_level.keys()), set(RiskLevel))
        self.assertEqual(summary.miles_by_level[RiskLevel.LOW], 5.0)
        self.assertEqual(summary.miles_by_level[RiskLevel.SEVERE], 7.5)
        self.assertEqual(summary.miles_by_level[RiskLevel.NO_TRAVEL], 0.0)
        self.assertTrue(summary.has_no_travel)

    def test_average_risk_is_distance_weighted(self) -> None:
        checkpoints = [_checkpoint(0, 90.0), _checkpoint(1, 10.0)]
        assessments = [_assessment(RiskLevel.LOW), _assessment(RiskLevel.SEVERE)]

        summary = summarize_route("route-1", 100.0, 3600.0, checkpoints, assessments)

        self.assertAlmostEqual(summary.average_risk, 1.3, places=6)

    def test_ranking_priority_follows_specified_order(self) -> None:
        fewer_severe = summarize_route(
            "route-1",
            100.0,
            5000.0,
            [_checkpoint(0, 5.0), _checkpoint(1, 30.0)],
            [_assessment(RiskLevel.SEVERE), _assessment(RiskLevel.HIGH)],
        )
        fewer_high_and_faster = summarize_route(
            "route-2",
            100.0,
            4000.0,
            [_checkpoint(0, 10.0), _checkpoint(1, 5.0)],
            [_assessment(RiskLevel.SEVERE), _assessment(RiskLevel.HIGH)],
        )

        ranked = rank_routes([fewer_high_and_faster, fewer_severe])

        self.assertEqual(ranked[0].route_id, "route-1")

    def test_with_equal_severe_fewer_high_wins_then_average_then_time(self) -> None:
        fewer_high = summarize_route(
            "route-1",
            100.0,
            6000.0,
            [_checkpoint(0, 10.0), _checkpoint(1, 5.0), _checkpoint(2, 85.0)],
            [_assessment(RiskLevel.SEVERE), _assessment(RiskLevel.HIGH), _assessment(RiskLevel.MODERATE)],
        )
        lower_average = summarize_route(
            "route-2",
            100.0,
            6000.0,
            [_checkpoint(0, 10.0), _checkpoint(1, 10.0), _checkpoint(2, 80.0)],
            [_assessment(RiskLevel.SEVERE), _assessment(RiskLevel.HIGH), _assessment(RiskLevel.LOW)],
        )
        faster = summarize_route(
            "route-3",
            100.0,
            5400.0,
            [_checkpoint(0, 10.0), _checkpoint(1, 10.0), _checkpoint(2, 80.0)],
            [_assessment(RiskLevel.SEVERE), _assessment(RiskLevel.HIGH), _assessment(RiskLevel.LOW)],
        )

        ranked_high = rank_routes([lower_average, fewer_high])
        self.assertEqual(ranked_high[0].route_id, "route-1")

        ranked_time = rank_routes([lower_average, faster])
        self.assertEqual(ranked_time[0].route_id, "route-3")

    def test_route_with_any_no_travel_loses_to_route_without_any(self) -> None:
        no_travel_route = summarize_route(
            "route-1",
            100.0,
            3000.0,
            [_checkpoint(0, 0.0), _checkpoint(1, 20.0)],
            [_assessment(RiskLevel.NO_TRAVEL), _assessment(RiskLevel.LOW)],
        )
        severe_route = summarize_route(
            "route-2",
            100.0,
            6000.0,
            [_checkpoint(0, 15.0)],
            [_assessment(RiskLevel.SEVERE)],
        )

        ranked = rank_routes([no_travel_route, severe_route])

        self.assertEqual(ranked[0].route_id, "route-2")

    def test_near_equal_values_within_rounding_tolerance_fall_through(self) -> None:
        route_one = summarize_route(
            "route-1",
            100.0,
            3660.0,
            [_checkpoint(0, 10.04), _checkpoint(1, 5.04)],
            [_assessment(RiskLevel.SEVERE), _assessment(RiskLevel.HIGH)],
        )
        route_two = summarize_route(
            "route-2",
            100.0,
            3600.0,
            [_checkpoint(0, 10.0), _checkpoint(1, 5.0)],
            [_assessment(RiskLevel.SEVERE), _assessment(RiskLevel.HIGH)],
        )

        ranked = rank_routes([route_one, route_two])

        self.assertEqual(ranked[0].route_id, "route-2")

    def test_stable_ordering_for_identical_summaries(self) -> None:
        route_one = summarize_route(
            "route-1",
            100.0,
            3600.0,
            [_checkpoint(0, 10.0)],
            [_assessment(RiskLevel.LOW)],
        )
        route_two = summarize_route(
            "route-2",
            100.0,
            3600.0,
            [_checkpoint(0, 10.0)],
            [_assessment(RiskLevel.LOW)],
        )

        ranked = rank_routes([route_one, route_two])

        self.assertEqual([summary.route_id for summary in ranked], ["route-1", "route-2"])

    def test_invalid_lengths_raise_value_error(self) -> None:
        with self.assertRaises(ValueError):
            summarize_route("route-1", 10.0, 100.0, [], [])

        with self.assertRaises(ValueError):
            summarize_route(
                "route-1",
                10.0,
                100.0,
                [_checkpoint(0, 1.0)],
                [],
            )

    def test_explain_recommendation_for_clear_severe_win(self) -> None:
        winner = summarize_route(
            "route-2",
            100.0,
            3600.0,
            [_checkpoint(0, 0.0), _checkpoint(1, 5.0)],
            [_assessment(RiskLevel.LOW), _assessment(RiskLevel.HIGH)],
        )
        runner_up = summarize_route(
            "route-1",
            100.0,
            3600.0,
            [_checkpoint(0, 41.0)],
            [_assessment(RiskLevel.SEVERE)],
        )

        explanation = explain_recommendation([winner, runner_up])

        self.assertIn("Route 2", explanation)
        self.assertIn("0.0 Severe miles", explanation)
        self.assertIn("41.0", explanation)

    def test_explain_recommendation_falls_to_time(self) -> None:
        winner = summarize_route(
            "route-1",
            100.0,
            3600.0,
            [_checkpoint(0, 10.0)],
            [_assessment(RiskLevel.HIGH)],
        )
        runner_up = summarize_route(
            "route-2",
            100.0,
            3900.0,
            [_checkpoint(0, 10.0)],
            [_assessment(RiskLevel.HIGH)],
        )

        explanation = explain_recommendation([winner, runner_up])

        self.assertEqual(explanation, "Fastest route; weather risk is equivalent.")

    def test_explain_recommendation_for_single_route(self) -> None:
        only = summarize_route(
            "route-1",
            100.0,
            3600.0,
            [_checkpoint(0, 10.0)],
            [_assessment(RiskLevel.LOW)],
        )

        explanation = explain_recommendation([only])

        self.assertEqual(explanation, "Route 1 is the only available route.")

    def test_explain_recommendation_when_all_routes_have_no_travel(self) -> None:
        winner = summarize_route(
            "route-2",
            100.0,
            3600.0,
            [_checkpoint(0, 5.0)],
            [_assessment(RiskLevel.NO_TRAVEL)],
        )
        runner_up = summarize_route(
            "route-1",
            100.0,
            3000.0,
            [_checkpoint(0, 12.0)],
            [_assessment(RiskLevel.NO_TRAVEL)],
        )

        explanation = explain_recommendation([winner, runner_up])

        self.assertIn("Every route has a No Travel segment", explanation)
        self.assertIn("Route 2", explanation)
        self.assertIn("5.0 miles", explanation)