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
from ..serializers import (
    IndexRowSerializer,
    MetricSerializer,
    MetricSeriesPointSerializer,
    RegionDashboardSerializer,
    RegionSerializer,
    TransitionSerializer,
)

GEO_MEASURES = ("cluster", "index")
INDEX_SCHEMES = ("equal", "pca", "expert")


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


class RegionList(APIView):
    """GET /api/regions/ — каталог регионов, участвующих в аналитике (85 субъектов)."""

    def get(self, request: Request) -> Response:
        data = queries.regions()
        log.info("regions", stage="api", rows=len(data))
        return Response(RegionSerializer(data, many=True).data)


class MetricList(APIView):
    """GET /api/metrics/?domain=<str> — каталог метрик ядра (опц. фильтр по домену)."""

    def get(self, request: Request) -> Response:
        domain = request.query_params.get("domain")
        data = queries.metrics(domain)
        log.info("metrics", stage="api", domain=domain, rows=len(data))
        return Response(MetricSerializer(data, many=True).data)


class MetricSeries(APIView):
    """GET /api/metrics/<id>/series/?okato=&from=&to= — ряд значений метрики по региону."""

    def get(self, request: Request, metric_id: int) -> Response:
        okato = request.query_params.get("okato")
        if not okato:
            return Response(
                {"detail": "параметр 'okato' обязателен"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            year_from = _optional_int(request.query_params.get("from"))
            year_to = _optional_int(request.query_params.get("to"))
        except ValueError:
            return Response(
                {"detail": "'from'/'to' должны быть целыми числами"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        data = queries.metric_series(metric_id, okato, year_from, year_to)
        log.info(
            "metric_series",
            stage="api",
            metric_id=metric_id,
            okato=okato,
            rows=len(data),
        )
        return Response(MetricSeriesPointSerializer(data, many=True).data)


def _optional_int(raw: str | None) -> int | None:
    """Разобрать необязательный целочисленный query-параметр (None пропускается)."""
    return None if raw is None else int(raw)


class RegionDashboard(APIView):
    """GET /api/regions/<okato>/?year=<int> — дашборд региона на год.

    Индекс по доменам (+B4: дельта к предыдущему году), тип/метка/типичность (A1),
    SHAP-топ метрик принадлежности, ранг по индексу. 404 — если данных за год нет.
    """

    def get(self, request: Request, okato: str) -> Response:
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
        data = queries.region_dashboard(okato, year)
        if data is None:
            return Response(
                {"detail": "нет данных индекса для региона за указанный год"},
                status=status.HTTP_404_NOT_FOUND,
            )
        log.info("region_dashboard", stage="api", okato=okato, year=year)
        return Response(RegionDashboardSerializer(data).data)


class IndexRanking(APIView):
    """GET /api/index/?year=<int>&scheme=equal|pca|expert — рейтинг регионов на год."""

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
        scheme = request.query_params.get("scheme", queries.MAP_INDEX_SCHEME)
        if scheme not in INDEX_SCHEMES:
            return Response(
                {"detail": f"'scheme' должен быть одним из {list(INDEX_SCHEMES)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        data = queries.index_ranking(year, scheme)
        log.info("index_ranking", stage="api", year=year, scheme=scheme, rows=len(data))
        return Response(IndexRowSerializer(data, many=True).data)


class Transitions(APIView):
    """GET /api/transitions/?okato=<str> — переходы между типами + тип траектории."""

    def get(self, request: Request) -> Response:
        okato = request.query_params.get("okato")
        data = queries.transitions_list(okato)
        log.info("transitions", stage="api", okato=okato, rows=len(data))
        return Response(TransitionSerializer(data, many=True).data)
