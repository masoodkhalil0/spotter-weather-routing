from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import Mock, patch

from django.core.cache import cache
from django.test import SimpleTestCase

from trips.services.timezones import TimezoneLookupError, lookup_timezone, resolve_departure


def _response(payload: object, status_code: int = 200) -> Mock:
    response = Mock()
    response.status_code = status_code
    response.json.return_value = payload
    return response


class TimezoneServiceTests(SimpleTestCase):
    def setUp(self) -> None:
        cache.clear()

    def test_resolve_departure_handles_dst_for_america_chicago_and_asia_karachi(self) -> None:
        july = resolve_departure(datetime(2026, 7, 10, 9, 0), "America/Chicago")
        january = resolve_departure(datetime(2026, 1, 10, 9, 0), "America/Chicago")
        karachi = resolve_departure(datetime(2026, 1, 10, 9, 0), "Asia/Karachi")

        self.assertEqual(july, datetime(2026, 7, 10, 14, 0, tzinfo=timezone.utc))
        self.assertEqual(january, datetime(2026, 1, 10, 15, 0, tzinfo=timezone.utc))
        self.assertEqual(karachi, datetime(2026, 1, 10, 4, 0, tzinfo=timezone.utc))

    def test_resolve_departure_preserves_aware_instant(self) -> None:
        aware = datetime.fromisoformat("2026-01-10T09:00:00+02:30")

        resolved = resolve_departure(aware, "America/Chicago")

        self.assertEqual(resolved, datetime(2026, 1, 10, 6, 30, tzinfo=timezone.utc))

    @patch("trips.services.timezones.requests.get")
    def test_lookup_timezone_returns_expected_shape_and_uses_cache(self, mock_get: Mock) -> None:
        mock_get.return_value = _response({"timezone": "America/Chicago"})

        first = lookup_timezone(41.8819, -87.6278)
        second = lookup_timezone(41.8821, -87.6281)

        self.assertEqual(first["timezone"], "America/Chicago")
        self.assertIsInstance(first["utc_offset_minutes"], int)
        self.assertEqual(first, second)
        self.assertEqual(mock_get.call_count, 1)

    @patch("trips.services.timezones.requests.get")
    def test_lookup_timezone_raises_on_upstream_failure_or_invalid_zone(self, mock_get: Mock) -> None:
        mock_get.side_effect = [
            _response({}, status_code=502),
            _response({"timezone": "Mars/Olympus"}),
        ]

        with self.assertRaisesMessage(TimezoneLookupError, "Timezone upstream failed."):
            lookup_timezone(10.0, 20.0)

        with self.assertRaisesMessage(TimezoneLookupError, "Timezone upstream failed."):
            lookup_timezone(11.0, 21.0)