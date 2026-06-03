"""Маршруты приложения core (каркас; расширяется в Ф6/Ф7)."""

from django.urls import path

from . import views

urlpatterns = [
    path("healthz/", views.healthz, name="healthz"),
]
