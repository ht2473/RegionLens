"""Корневая маршрутизация проекта. Расширяется в Ф6 (API) / Ф7 (страницы) / Ф10."""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("core.urls")),
]
