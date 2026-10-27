"""Request serializers that keep HTTP validation separate from pure services."""

from __future__ import annotations

from rest_framework import serializers

from trips.services.checkpoints import haversine_miles
from trips.services.heatmap import MAX_HEATMAP_HOURS


MIN_TRIP_DISTANCE_MILES = 0.5
ALLOWED_INTERVALS = (10, 25, 50)


class CoordinateSerializer(serializers.Serializer):
    """Validate one latitude/longitude pair before service-level processing."""

    lat = serializers.FloatField(min_value=-90.0, max_value=90.0)
    lon = serializers.FloatField(min_value=-180.0, max_value=180.0)


class NaiveAwareDateTimeField(serializers.DateTimeField):
    """Keep parsed datetimes exactly as provided by the client."""

    def enforce_timezone(self, value):
        # DRF would otherwise make naive values UTC-aware before the view can use the origin zone.
        return value


class AnalyzeRequestSerializer(serializers.Serializer):
    """Validate analyze-trip inputs and normalize them for the API view."""

    origin = CoordinateSerializer()
    destination = CoordinateSerializer()
    departure = NaiveAwareDateTimeField()
    load_weight_lb = serializers.FloatField(min_value=0.0, max_value=80000.0)
    interval_miles = serializers.ChoiceField(choices=ALLOWED_INTERVALS, required=False)

    def validate(self, attrs):
        """Require origin and destination to be meaningfully different."""

        origin = attrs["origin"]
        destination = attrs["destination"]
        origin_point = (origin["lat"], origin["lon"])
        destination_point = (destination["lat"], destination["lon"])
        if haversine_miles(origin_point, destination_point) < MIN_TRIP_DISTANCE_MILES:
            raise serializers.ValidationError(
                {"non_field_errors": ["Origin and destination must be at least 0.5 miles apart."]}
            )
        attrs["origin_point"] = origin_point
        attrs["destination_point"] = destination_point
        return attrs

    @property
    def origin_point(self) -> tuple[float, float]:
        """Return the validated origin as a plain service tuple."""

        return self.validated_data["origin_point"]

    @property
    def destination_point(self) -> tuple[float, float]:
        """Return the validated destination as a plain service tuple."""

        return self.validated_data["destination_point"]

    @property
    def departure_aware(self):
        """Return the validated departure timestamp in aware form."""

        return self.validated_data["departure"]


class HeatmapRequestSerializer(AnalyzeRequestSerializer):
    """Validate heatmap inputs using the same trip fields minus interval_miles."""

    hours = serializers.IntegerField(
        min_value=1,
        max_value=MAX_HEATMAP_HOURS,
        required=False,
        default=MAX_HEATMAP_HOURS,
    )

    def get_fields(self):
        fields = super().get_fields()
        fields.pop("interval_miles", None)
        return fields