"""Shared datetime formatting helpers for trip services."""

from __future__ import annotations

from datetime import datetime, timezone


def iso_utc(value: datetime) -> str:
    """Return an ISO-8601 string normalized to UTC with second precision and Z suffix."""

    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")