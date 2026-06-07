"""Маршруты приложения core (каркас; расширяется в Ф6/Ф7)."""

from django.urls import include, path

from . import views

urlpatterns = [
    path("healthz/", views.healthz, name="healthz"),
    path("api/", include("core.api.urls")),
]
