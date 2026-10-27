"""JSON-only API views that adapt HTTP concerns to pure trip services."""

from __future__ import annotations

import logging
from datetime import timedelta, timezone

from rest_framework import status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from django.utils import timezone as django_timezone

from trips.api.serializers import (
    AnalyzeRequestSerializer,
    HeatmapRequestSerializer,
)
from trips.services.analysis import analyze_trip
from trips.services.heatmap import build_heatmap
from trips.services.geocoding import GeocodingError, search_places
from trips.services.routing import NoRouteFoundError, RoutingServiceError, get_routes
from trips.services.timezones import (
    TimezoneLookupError,
    lookup_timezone,
    resolve_departure,
)
from trips.services.weather import WeatherRateLimitError, WeatherServiceError


logger = logging.getLogger("trips")
MIN_DEPARTURE_AGE = timedelta(hours=1)
MAX_DEPARTURE_AHEAD = timedelta(days=10)


def _validate_departure_window(departure_utc):
    """Apply the public departure time window after UTC resolution."""

    now = django_timezone.now()
    if departure_utc < now - MIN_DEPARTURE_AGE:
        return "Departure must be within the last hour or later."
    if departure_utc > now + MAX_DEPARTURE_AHEAD:
        return "Departure must be within the next 10 days."
    return None


def _resolve_origin_timezone(origin_point, departure):
    """Resolve origin timezone, soft-failing only for aware departures."""

    if departure.tzinfo is None or departure.utcoffset() is None:
        timezone_data = lookup_timezone(origin_point[0], origin_point[1])
        return timezone_data["timezone"], resolve_departure(departure, timezone_data["timezone"])

    try:
        timezone_data = lookup_timezone(origin_point[0], origin_point[1])
    except TimezoneLookupError:
        return None, departure.astimezone(timezone.utc)
    return timezone_data["timezone"], departure.astimezone(timezone.utc)


class HealthView(APIView):
    """Provide a tiny liveness endpoint for health checks."""

    def get(self, request):
        return Response({"status": "ok"})


class GeocodeView(APIView):
    """Validate a simple place query and shield callers from upstream geocoder details."""

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "geocode"

    def get(self, request):
        query = request.query_params.get("q", "")
        normalized_query = " ".join(query.split())
        if not normalized_query:
            return Response({"q": ["This query parameter is required."]}, status=status.HTTP_400_BAD_REQUEST)
        if len(normalized_query) < 2 or len(normalized_query) > 200:
            return Response(
                {"q": ["Ensure this query parameter has between 2 and 200 characters."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            places = search_places(normalized_query)
        except GeocodingError as exc:
            logger.warning("Geocoding upstream failed: %s", exc)
            return Response(
                {"detail": "Geocoding upstream failed."},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except Exception:
            logger.exception("Unexpected error in geocode endpoint")
            return Response(
                {"detail": "Internal server error."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(
            {
                "results": [
                    {"label": place.label, "lat": place.lat, "lon": place.lon}
                    for place in places
                ]
            }
        )


class AnalyzeView(APIView):
    """Validate trip inputs, call the pure analysis pipeline, and map failures cleanly."""

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "analyze"

    def post(self, request):
        serializer = AnalyzeRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            origin_timezone, departure_utc = _resolve_origin_timezone(
                serializer.origin_point,
                serializer.departure_aware,
            )
            departure_error = _validate_departure_window(departure_utc)
            if departure_error is not None:
                return Response({"departure": [departure_error]}, status=status.HTTP_400_BAD_REQUEST)
            result = analyze_trip(
                serializer.origin_point,
                serializer.destination_point,
                departure_utc,
                serializer.validated_data["load_weight_lb"],
                serializer.validated_data.get("interval_miles"),
                origin_timezone=origin_timezone,
            )
        except TimezoneLookupError as exc:
            logger.warning("Timezone upstream failed: %s", exc)
            return Response(
                {"detail": "Timezone upstream failed."},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except NoRouteFoundError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except RoutingServiceError as exc:
            logger.warning("Routing upstream failed: %s", exc)
            return Response(
                {"detail": "Routing upstream failed."},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except WeatherRateLimitError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except WeatherServiceError as exc:
            logger.warning("Weather upstream failed: %s", exc)
            return Response(
                {"detail": "Weather upstream failed."},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except Exception:
            logger.exception("Unexpected error in analyze endpoint")
            return Response(
                {"detail": "Internal server error."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(result)


class HeatmapView(APIView):
    """Validate trip inputs, fetch routes, and build a compact weather-risk heatmap."""

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "heatmap"

    def post(self, request):
        serializer = HeatmapRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            origin_timezone, departure_utc = _resolve_origin_timezone(
                serializer.origin_point,
                serializer.departure_aware,
            )
            departure_error = _validate_departure_window(departure_utc)
            if departure_error is not None:
                return Response({"departure": [departure_error]}, status=status.HTTP_400_BAD_REQUEST)
            routes = get_routes(
                serializer.origin_point,
                serializer.destination_point,
            )
            result = build_heatmap(
                routes,
                departure_utc,
                serializer.validated_data["load_weight_lb"],
                hours=serializer.validated_data["hours"],
                origin_timezone=origin_timezone,
            )
        except TimezoneLookupError as exc:
            logger.warning("Timezone upstream failed: %s", exc)
            return Response(
                {"detail": "Timezone upstream failed."},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except NoRouteFoundError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except RoutingServiceError as exc:
            logger.warning("Routing upstream failed: %s", exc)
            return Response(
                {"detail": "Routing upstream failed."},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except WeatherRateLimitError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except WeatherServiceError as exc:
            logger.warning("Weather upstream failed: %s", exc)
            return Response(
                {"detail": "Weather upstream failed."},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except Exception:
            logger.exception("Unexpected error in heatmap endpoint")
            return Response(
                {"detail": "Internal server error."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(result)


class TimezoneView(APIView):
    """Resolve an origin timezone from latitude and longitude."""

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "timezone"

    def get(self, request):
        try:
            lat = float(request.query_params.get("lat", ""))
            lon = float(request.query_params.get("lon", ""))
        except (TypeError, ValueError):
            return Response(
                {"detail": "Latitude and longitude must be valid numbers."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not -90.0 <= lat <= 90.0 or not -180.0 <= lon <= 180.0:
            return Response(
                {"detail": "Latitude must be between -90 and 90 and longitude between -180 and 180."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            return Response(lookup_timezone(lat, lon))
        except TimezoneLookupError as exc:
            logger.warning("Timezone upstream failed: %s", exc)
            return Response(
                {"detail": "Timezone upstream failed."},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except Exception:
            logger.exception("Unexpected error in timezone endpoint")
            return Response(
                {"detail": "Internal server error."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )