"""JSON-only API views that adapt HTTP concerns to pure trip services."""

from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from trips.api.serializers import AnalyzeRequestSerializer
from trips.services.analysis import analyze_trip
from trips.services.geocoding import GeocodingError, search_places
from trips.services.routing import RoutingServiceError
from trips.services.weather import WeatherServiceError


logger = logging.getLogger("trips")


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
        except GeocodingError:
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
            result = analyze_trip(
                serializer.origin_point,
                serializer.destination_point,
                serializer.departure_aware,
                serializer.validated_data["load_weight_lb"],
                serializer.validated_data.get("interval_miles"),
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except RoutingServiceError:
            return Response(
                {"detail": "Routing upstream failed."},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except WeatherServiceError:
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