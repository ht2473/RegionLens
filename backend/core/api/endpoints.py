"""DRF-эндпойнты ядра (Ф6): read-only чтение предрассчитанной аналитики из DuckDB.

Тонкий слой контроллера: валидация query-параметров → вызов core.queries → Response.
Вся работа с хранилищем — в core.queries (контракт раньше кода, Хартия §2). Отклик
быстрый: читается уже посчитанное, без вычислений на лету (цель <200 мс).
"""

from __future__ import annotations

from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from pipeline.logging_setup import log

from .. import queries

GEO_MEASURES = ("cluster", "index")


class GeoLayer(APIView):
    """GET /api/geo/layer/?year=<int>&measure=cluster|index — слой карты на год.

    Возвращает список регионов со значением для раскраски карты. measure=cluster даёт
    cluster_id/метку/distance_to_centroid (A1); measure=index — total_score индекса.
    """

    def get(self, request: Request) -> Response:
        raw_year = request.query_params.get("year")
        if raw_year is None:
            return Response(
                {"detail": "параметр 'year' обязателен"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            year = int(raw_year)
        except ValueError:
            return Response(
                {"detail": "'year' должен быть целым числом"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        measure = request.query_params.get("measure", "cluster")
        if measure not in GEO_MEASURES:
            return Response(
                {"detail": f"'measure' должен быть одним из {list(GEO_MEASURES)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        data = queries.geo_layer(year, measure)
        log.info("geo_layer", stage="api", year=year, measure=measure, rows=len(data))
        return Response(data)
