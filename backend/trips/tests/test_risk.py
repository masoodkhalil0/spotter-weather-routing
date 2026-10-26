from django.test import SimpleTestCase

from trips.services.risk import (
    RiskLevel,
    WeatherConditions,
    assess_risk,
    classify_rain,
    classify_snow,
    classify_wind,
)


class WindClassificationTests(SimpleTestCase):
    def test_wind_band_boundaries(self) -> None:
        cases = [
            (0.0, RiskLevel.LOW),
            (24.9, RiskLevel.LOW),
            (25.0, RiskLevel.MODERATE),
            (34.9, RiskLevel.MODERATE),
            (35.0, RiskLevel.HIGH),
            (44.9, RiskLevel.HIGH),
            (45.0, RiskLevel.SEVERE),
            (54.9, RiskLevel.SEVERE),
            (55.0, RiskLevel.NO_TRAVEL),
            (80.0, RiskLevel.NO_TRAVEL),
        ]

        for mph, expected in cases:
            with self.subTest(mph=mph):
                self.assertEqual(classify_wind(mph), expected)


class RainClassificationTests(SimpleTestCase):
    def test_rain_band_boundaries(self) -> None:
        cases = [
            (0.0, RiskLevel.LOW),
            (0.099, RiskLevel.LOW),
            (0.10, RiskLevel.MODERATE),
            (0.249, RiskLevel.MODERATE),
            (0.25, RiskLevel.HIGH),
            (0.499, RiskLevel.HIGH),
            (0.50, RiskLevel.SEVERE),
            (1.00, RiskLevel.SEVERE),
            (1.001, RiskLevel.NO_TRAVEL),
            (2.0, RiskLevel.NO_TRAVEL),
        ]

        for in_hr, expected in cases:
            with self.subTest(in_hr=in_hr):
                self.assertEqual(classify_rain(in_hr), expected)


class SnowClassificationTests(SimpleTestCase):
    def test_snow_band_boundaries(self) -> None:
        cases = [
            (0.0, RiskLevel.LOW),
            (0.499, RiskLevel.LOW),
            (0.5, RiskLevel.MODERATE),
            (0.999, RiskLevel.MODERATE),
            (1.0, RiskLevel.HIGH),
            (1.999, RiskLevel.HIGH),
            (2.0, RiskLevel.SEVERE),
            (3.0, RiskLevel.SEVERE),
            (3.001, RiskLevel.NO_TRAVEL),
            (5.0, RiskLevel.NO_TRAVEL),
        ]

        for in_hr, expected in cases:
            with self.subTest(in_hr=in_hr):
                self.assertEqual(classify_snow(in_hr), expected)


class AssessRiskTests(SimpleTestCase):
    def test_combined_conditions_take_max(self) -> None:
        assessment = assess_risk(
            WeatherConditions(wind_mph=26.0, rain_in_hr=0.30, snow_in_hr=0.0),
            load_weight_lb=10000.0,
        )

        self.assertEqual(assessment.wind, RiskLevel.MODERATE)
        self.assertEqual(assessment.rain, RiskLevel.HIGH)
        self.assertEqual(assessment.snow, RiskLevel.LOW)
        self.assertEqual(assessment.level, RiskLevel.HIGH)

    def test_wind_no_travel_threshold_applies_for_any_load(self) -> None:
        assessment = assess_risk(
            WeatherConditions(wind_mph=55.0, rain_in_hr=0.0, snow_in_hr=0.0),
            load_weight_lb=0.0,
        )

        self.assertEqual(assessment.level, RiskLevel.NO_TRAVEL)

    def test_load_rule_over_30000_not_triggered_at_exact_weight(self) -> None:
        assessment = assess_risk(
            WeatherConditions(wind_mph=45.0, rain_in_hr=0.0, snow_in_hr=0.0),
            load_weight_lb=30000.0,
        )

        self.assertEqual(assessment.level, RiskLevel.SEVERE)
        self.assertFalse(any("30,000" in reason for reason in assessment.reasons))

    def test_load_rule_over_30000_triggers_no_travel(self) -> None:
        assessment = assess_risk(
            WeatherConditions(wind_mph=54.9, rain_in_hr=0.0, snow_in_hr=0.0),
            load_weight_lb=30001.0,
        )

        self.assertEqual(assessment.level, RiskLevel.NO_TRAVEL)
        self.assertTrue(any("30,000" in reason for reason in assessment.reasons))

    def test_load_rule_over_40000_not_triggered_at_exact_weight(self) -> None:
        assessment = assess_risk(
            WeatherConditions(wind_mph=35.0, rain_in_hr=0.0, snow_in_hr=0.0),
            load_weight_lb=40000.0,
        )

        self.assertEqual(assessment.level, RiskLevel.HIGH)
        self.assertFalse(any("40,000" in reason for reason in assessment.reasons))

    def test_load_rule_over_40000_triggers_at_least_severe(self) -> None:
        assessment = assess_risk(
            WeatherConditions(wind_mph=44.9, rain_in_hr=0.0, snow_in_hr=0.0),
            load_weight_lb=40001.0,
        )

        self.assertEqual(assessment.level, RiskLevel.SEVERE)
        self.assertTrue(any("40,000" in reason for reason in assessment.reasons))

    def test_load_rule_never_lowers_higher_level(self) -> None:
        assessment = assess_risk(
            WeatherConditions(wind_mph=40.0, rain_in_hr=1.1, snow_in_hr=0.0),
            load_weight_lb=40001.0,
        )

        self.assertEqual(assessment.level, RiskLevel.NO_TRAVEL)

    def test_reasons_added_for_each_condition_at_moderate_or_above(self) -> None:
        assessment = assess_risk(
            WeatherConditions(wind_mph=25.0, rain_in_hr=0.25, snow_in_hr=0.5),
            load_weight_lb=1000.0,
        )

        self.assertEqual(len(assessment.reasons), 3)

    def test_negative_values_raise_value_error(self) -> None:
        with self.assertRaises(ValueError):
            classify_wind(-0.1)

        with self.assertRaises(ValueError):
            classify_rain(-0.1)

        with self.assertRaises(ValueError):
            classify_snow(-0.1)

        with self.assertRaises(ValueError):
            assess_risk(
                WeatherConditions(wind_mph=-1.0, rain_in_hr=0.0, snow_in_hr=0.0),
                load_weight_lb=100.0,
            )

        with self.assertRaises(ValueError):
            assess_risk(
                WeatherConditions(wind_mph=0.0, rain_in_hr=-0.1, snow_in_hr=0.0),
                load_weight_lb=100.0,
            )

        with self.assertRaises(ValueError):
            assess_risk(
                WeatherConditions(wind_mph=0.0, rain_in_hr=0.0, snow_in_hr=-0.1),
                load_weight_lb=100.0,
            )

        with self.assertRaises(ValueError):
            assess_risk(
                WeatherConditions(wind_mph=0.0, rain_in_hr=0.0, snow_in_hr=0.0),
                load_weight_lb=-1.0,
            )