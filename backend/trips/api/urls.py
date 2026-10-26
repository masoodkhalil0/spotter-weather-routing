"""URL routes for the trips API."""

from django.urls import path

from trips.api.views import AnalyzeView, GeocodeView, HealthView


urlpatterns = [
    path("health/", HealthView.as_view(), name="api-health"),
    path("geocode/", GeocodeView.as_view(), name="api-geocode"),
    path("analyze/", AnalyzeView.as_view(), name="api-analyze"),
]