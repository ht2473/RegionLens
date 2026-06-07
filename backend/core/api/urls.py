"""Маршруты API ядра (Ф6). Подключаются под префиксом /api/ из core.urls.

Каталог эндпойнтов растёт по модулям Ф6 (regions/metrics/typology/index/transitions/
compare) и расширяется в Ф10/Ф11. Сейчас — слой карты geo/layer.
"""

from django.urls import path

from . import endpoints

urlpatterns = [
    path("geo/layer/", endpoints.GeoLayer.as_view(), name="geo-layer"),
]
