from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import Mock, patch

from django.core.cache import cache
from django.test import SimpleTestCase
from requests.exceptions import Timeout

from trips.services.risk import WeatherConditions
from trips.services.weather import HourlyForecast, WeatherServiceError, conditions_at, fetch_forecasts


def _response(payload: object, status_code: int = 200) -> Mock:
    response = Mock()
    response.status_code = status_code
    response.json.return_value = payload
    return response


def _forecast_item(
    *,
    time_values: list[str] | None = None,
    wind_values: list[float | None] | None = None,
    rain_values: list[float | None] | None = None,
    showers_values: list[float | None] | None = None,
    snow_values: list[float | None] | None = None,
) -> dict:
    return {
        "hourly": {
            "time": time_values or ["2026-01-01T10:00", "2026-01-01T11:00"],
            "wind_speed_10m": wind_values or [10.0, 11.0],
            "rain": rain_values or [0.1, 0.2],
            "showers": showers_values or [0.05, 0.05],
            "snowfall": snow_values or [0.0, 0.1],
        }
    }


class WeatherTests(SimpleTestCase):
    def setUp(self) -> None:
        cache.clear()
        self.start = date(2026, 1, 1)
        self.end = date(2026, 1, 1)

    @patch("trips.services.weather.sleep", return_value=None)
    @patch("trips.services.weather.requests.get")
    def test_single_location_object_response_is_normalized(self, mock_get: Mock, _: Mock) -> None:
        mock_get.return_value = _response(_forecast_item())

        forecasts = fetch_forecasts([(40.1234, -75.5678)], self.start, self.end)

        self.assertEqual(len(forecasts), 1)
        self.assertEqual(mock_get.call_count, 1)
        self.assertEqual(forecasts[0].wind_mph, (10.0, 11.0))

    @patch("trips.services.weather.sleep", return_value=None)
    @patch("trips.services.weather.requests.get")
    def test_multi_location_response_keeps_order(self, mock_get: Mock, _: Mock) -> None:
        mock_get.return_value = _response(
            [
                _forecast_item(wind_values=[1.0, 2.0]),
                _forecast_item(wind_values=[3.0, 4.0]),
            ]
        )

        forecasts = fetch_forecasts([(10.0, 20.0), (30.0, 40.0)], self.start, self.end)

        self.assertEqual(forecasts[0].wind_mph, (1.0, 2.0))
        self.assertEqual(forecasts[1].wind_mph, (3.0, 4.0))

    @patch("trips.services.weather.sleep", return_value=None)
    @patch("trips.services.weather.requests.get")
    def test_120_points_produce_three_http_requests(self, mock_get: Mock, _: Mock) -> None:
        mock_get.side_effect = [
            _response([_forecast_item()] * 50),
            _response([_forecast_item()] * 50),
            _response([_forecast_item()] * 20),
        ]

        points = [(float(index), float(index)) for index in range(120)]
        forecasts = fetch_forecasts(points, self.start, self.end)

        self.assertEqual(len(forecasts), 120)
        self.assertEqual(mock_get.call_count, 3)

    @patch("trips.services.weather.sleep", return_value=None)
    @patch("trips.services.weather.requests.get")
    def test_duplicate_points_produce_one_request_entry_but_full_output(self, mock_get: Mock, _: Mock) -> None:
        mock_get.return_value = _response([_forecast_item()])

        forecasts = fetch_forecasts([(10.001, 20.001), (10.004, 20.004)], self.start, self.end)

        self.assertEqual(len(forecasts), 2)
        self.assertEqual(forecasts[0], forecasts[1])
        params = mock_get.call_args.kwargs["params"]
        self.assertEqual(params["latitude"], "10.0")
        self.assertEqual(params["longitude"], "20.0")

    @patch("trips.services.weather.sleep", return_value=None)
    @patch("trips.services.weather.requests.get")
    def test_none_values_become_zero_and_rain_showers_are_summed(self, mock_get: Mock, _: Mock) -> None:
        mock_get.return_value = _response(
            _forecast_item(
                wind_values=[None, 5.0],
                rain_values=[0.2, None],
                showers_values=[None, 0.3],
                snow_values=[None, 0.1],
            )
        )

        forecast = fetch_forecasts([(40.0, -75.0)], self.start, self.end)[0]

        self.assertEqual(forecast.wind_mph, (0.0, 5.0))
        self.assertEqual(forecast.rain_in, (0.2, 0.3))
        self.assertEqual(forecast.snow_in, (0.0, 0.1))

    @patch("trips.services.weather.sleep", return_value=None)
    @patch("trips.services.weather.requests.get")
    def test_caching_makes_second_identical_call_use_zero_http_requests(self, mock_get: Mock, _: Mock) -> None:
        mock_get.return_value = _response(_forecast_item())

        first = fetch_forecasts([(40.0, -75.0)], self.start, self.end)
        second = fetch_forecasts([(40.0, -75.0)], self.start, self.end)

        self.assertEqual(first, second)
        self.assertEqual(mock_get.call_count, 1)

    @patch("trips.services.weather.sleep", return_value=None)
    @patch("trips.services.weather.requests.get")
    def test_retry_once_on_500_then_success(self, mock_get: Mock, _: Mock) -> None:
        mock_get.side_effect = [_response({}, status_code=500), _response(_forecast_item())]

        forecasts = fetch_forecasts([(40.0, -75.0)], self.start, self.end)

        self.assertEqual(len(forecasts), 1)
        self.assertEqual(mock_get.call_count, 2)

    @patch("trips.services.weather.sleep", return_value=None)
    @patch("trips.services.weather.requests.get")
    def test_two_failures_raise_weather_service_error(self, mock_get: Mock, _: Mock) -> None:
        mock_get.side_effect = [Timeout(), Timeout()]

        with self.assertRaisesMessage(WeatherServiceError, "Weather service timed out"):
            fetch_forecasts([(40.0, -75.0)], self.start, self.end)

        self.assertEqual(mock_get.call_count, 2)

    @patch("trips.services.weather.sleep", return_value=None)
    @patch("trips.services.weather.requests.get")
    def test_malformed_json_raises_weather_service_error(self, mock_get: Mock, _: Mock) -> None:
        response = Mock()
        response.status_code = 200
        response.json.side_effect = ValueError("bad json")
        mock_get.return_value = response

        with self.assertRaisesMessage(WeatherServiceError, "Weather service returned malformed data"):
            fetch_forecasts([(40.0, -75.0)], self.start, self.end)

    def test_conditions_at_picks_nearest_hour_and_validates_time(self) -> None:
        forecast = HourlyForecast(
            times=(
                datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc),
                datetime(2026, 1, 1, 11, 0, tzinfo=timezone.utc),
            ),
            wind_mph=(10.0, 20.0),
            rain_in=(0.1, 0.2),
            snow_in=(0.0, 0.3),
        )

        early = conditions_at(forecast, datetime(2026, 1, 1, 10, 20, tzinfo=timezone.utc))
        late = conditions_at(forecast, datetime(2026, 1, 1, 10, 40, tzinfo=timezone.utc))

        self.assertEqual(early, WeatherConditions(wind_mph=10.0, rain_in_hr=0.1, snow_in_hr=0.0))
        self.assertEqual(late, WeatherConditions(wind_mph=20.0, rain_in_hr=0.2, snow_in_hr=0.3))

        with self.assertRaises(ValueError):
            conditions_at(forecast, datetime(2026, 1, 1, 10, 20))

        with self.assertRaisesMessage(WeatherServiceError, "forecast does not cover this time"):
            conditions_at(forecast, datetime(2026, 1, 1, 13, 0, tzinfo=timezone.utc))