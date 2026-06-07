"""DRF-эндпойнты ядра (Ф6): read-only чтение предрассчитанной аналитики из DuckDB.

Тонкий слой контроллера: валидация query-параметров → вызов core.queries → Response.
Вся работа с хранилищем — в core.queries (контракт раньше кода, Хартия §2). Отклик
быстрый: читается уже посчитанное, без вычислений на лету (цель <200 мс). Каждый
эндпойнт декорирован @extend_schema — это даёт типизированную OpenAPI-схему и Swagger.
"""

from __future__ import annotations

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from pipeline.logging_setup import log

from .. import queries
from ..serializers import (
    ClusterProfileRowSerializer,
    CompareRowSerializer,
    GeoLayerPointSerializer,
    IndexRowSerializer,
    MetricSerializer,
    MetricSeriesPointSerializer,
    RegionDashboardSerializer,
    RegionSerializer,
    TransitionSerializer,
    TypologyExplainSerializer,
    TypologyRowSerializer,
)

GEO_MEASURES = ("cluster", "index")
INDEX_SCHEMES = ("equal", "pca", "expert")
COMPARE_MIN, COMPARE_MAX = 2, 3

# Переиспользуемые описания query-параметров для OpenAPI-схемы (Swagger).
P_YEAR = OpenApiParameter(
    "year", OpenApiTypes.INT, required=True, description="Год (окно 2010-2024)"
)
P_MEASURE = OpenApiParameter(
    "measure", OpenApiTypes.STR, enum=list(GEO_MEASURES), description="Мера слоя карты"
)
P_DOMAIN = OpenApiParameter("domain", OpenApiTypes.STR, description="Фильтр по домену")
P_OKATO = OpenApiParameter("okato", OpenApiTypes.STR, description="Код ОКАТО региона")
P_FROM = OpenApiParameter("from", OpenApiTypes.INT, description="Нижняя граница года")
P_TO = OpenApiParameter("to", OpenApiTypes.INT, description="Верхняя граница года")
P_SCHEME = OpenApiParameter(
    "scheme", OpenApiTypes.STR, enum=list(INDEX_SCHEMES), description="Схема весов индекса"
)
P_K = OpenApiParameter("k", OpenApiTypes.INT, description="Число кластеров (по умолчанию chosen_k)")
P_CLUSTER = OpenApiParameter("cluster_id", OpenApiTypes.INT, required=True, description="Тип (id)")
P_OKATO_MULTI = OpenApiParameter(
    "okato", OpenApiTypes.STR, many=True, required=True, description="2-3 кода ОКАТО"
)


def _parse_year(request: Request) -> tuple[int | None, Response | None]:
    """Разобрать обязательный целочисленный query-параметр 'year'.

    Возвращает (year, None) при успехе или (None, Response-400) при ошибке.
    """
    raw = request.query_params.get("year")
    if raw is None:
        return None, Response(
            {"detail": "параметр 'year' обязателен"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        return int(raw), None
    except ValueError:
        return None, Response(
            {"detail": "'year' должен быть целым числом"},
            status=status.HTTP_400_BAD_REQUEST,
        )


def _optional_int(raw: str | None) -> int | None:
    """Разобрать необязательный целочисленный query-параметр (None пропускается)."""
    return None if raw is None else int(raw)


class GeoLayer(APIView):
    """GET /api/geo/layer/?year=<int>&measure=cluster|index — слой карты на год.

    Возвращает список регионов со значением для раскраски карты. measure=cluster даёт
    cluster_id/метку/distance_to_centroid (A1); measure=index — total_score индекса.
    """

    @extend_schema(
        parameters=[P_YEAR, P_MEASURE],
        responses=GeoLayerPointSerializer(many=True),
        summary="Слой карты на год",
    )
    def get(self, request: Request) -> Response:
        year, err = _parse_year(request)
        if err is not None:
            return err
        assert year is not None
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

    @extend_schema(responses=RegionSerializer(many=True), summary="Каталог регионов")
    def get(self, request: Request) -> Response:
        data = queries.regions()
        log.info("regions", stage="api", rows=len(data))
        return Response(RegionSerializer(data, many=True).data)


class MetricList(APIView):
    """GET /api/metrics/?domain=<str> — каталог метрик ядра (опц. фильтр по домену)."""

    @extend_schema(
        parameters=[P_DOMAIN],
        responses=MetricSerializer(many=True),
        summary="Каталог метрик ядра",
    )
    def get(self, request: Request) -> Response:
        domain = request.query_params.get("domain")
        data = queries.metrics(domain)
        log.info("metrics", stage="api", domain=domain, rows=len(data))
        return Response(MetricSerializer(data, many=True).data)


class MetricSeries(APIView):
    """GET /api/metrics/<id>/series/?okato=&from=&to= — ряд значений метрики по региону."""

    @extend_schema(
        parameters=[P_OKATO, P_FROM, P_TO],
        responses=MetricSeriesPointSerializer(many=True),
        summary="Временной ряд метрики по региону",
    )
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
        log.info("metric_series", stage="api", metric_id=metric_id, okato=okato, rows=len(data))
        return Response(MetricSeriesPointSerializer(data, many=True).data)


class RegionDashboard(APIView):
    """GET /api/regions/<okato>/?year=<int> — дашборд региона на год.

    Индекс по доменам (+B4: дельта к предыдущему году), тип/метка/типичность (A1),
    SHAP-топ метрик принадлежности, ранг по индексу. 404 — если данных за год нет.
    """

    @extend_schema(
        operation_id="region_dashboard",
        parameters=[P_YEAR],
        responses=RegionDashboardSerializer,
        summary="Дашборд региона на год",
    )
    def get(self, request: Request, okato: str) -> Response:
        year, err = _parse_year(request)
        if err is not None:
            return err
        assert year is not None  # сужение типа после проверки err
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

    @extend_schema(
        parameters=[P_YEAR, P_SCHEME],
        responses=IndexRowSerializer(many=True),
        summary="Рейтинг регионов по индексу",
    )
    def get(self, request: Request) -> Response:
        year, err = _parse_year(request)
        if err is not None:
            return err
        assert year is not None
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

    @extend_schema(
        parameters=[P_OKATO],
        responses=TransitionSerializer(many=True),
        summary="Переходы между типами",
    )
    def get(self, request: Request) -> Response:
        okato = request.query_params.get("okato")
        data = queries.transitions_list(okato)
        log.info("transitions", stage="api", okato=okato, rows=len(data))
        return Response(TransitionSerializer(data, many=True).data)


class Typology(APIView):
    """GET /api/typology/?year=<int>&k=<int> — принадлежность регионов к типам на год."""

    @extend_schema(
        parameters=[P_YEAR, P_K],
        responses=TypologyRowSerializer(many=True),
        summary="Типология регионов на год",
    )
    def get(self, request: Request) -> Response:
        year, err = _parse_year(request)
        if err is not None:
            return err
        assert year is not None
        try:
            k = _optional_int(request.query_params.get("k"))
        except ValueError:
            return Response(
                {"detail": "'k' должен быть целым числом"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        data = queries.typology(year, k)
        log.info("typology", stage="api", year=year, k=k, rows=len(data))
        return Response(TypologyRowSerializer(data, many=True).data)


class TypologyExplain(APIView):
    """GET /api/typology/<okato>/explain/?year=<int> — SHAP принадлежности к типу."""

    @extend_schema(
        parameters=[P_YEAR],
        responses=TypologyExplainSerializer,
        summary="SHAP-объяснение принадлежности к типу",
    )
    def get(self, request: Request, okato: str) -> Response:
        year, err = _parse_year(request)
        if err is not None:
            return err
        assert year is not None
        data = queries.typology_explain(okato, year)
        if data is None:
            return Response(
                {"detail": "регион отсутствует в типологии за указанный год"},
                status=status.HTTP_404_NOT_FOUND,
            )
        log.info("typology_explain", stage="api", okato=okato, year=year)
        return Response(TypologyExplainSerializer(data).data)


class ClusterProfile(APIView):
    """GET /api/typology/profile/?year=<int>&cluster_id=<int>&k=<int> — профиль типа."""

    @extend_schema(
        parameters=[P_YEAR, P_CLUSTER, P_K],
        responses=ClusterProfileRowSerializer(many=True),
        summary="Профиль типа (средний z метрик)",
    )
    def get(self, request: Request) -> Response:
        year, err = _parse_year(request)
        if err is not None:
            return err
        assert year is not None
        raw_cluster = request.query_params.get("cluster_id")
        if raw_cluster is None:
            return Response(
                {"detail": "параметр 'cluster_id' обязателен"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            cluster_id = int(raw_cluster)
            k = _optional_int(request.query_params.get("k"))
        except ValueError:
            return Response(
                {"detail": "'cluster_id'/'k' должны быть целыми числами"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        data = queries.cluster_profile(year, cluster_id, k)
        log.info("cluster_profile", stage="api", year=year, cluster_id=cluster_id, rows=len(data))
        return Response(ClusterProfileRowSerializer(data, many=True).data)


class Compare(APIView):
    """GET /api/compare/?okato=<a>&okato=<b>[&okato=<c>]&year=<int> — gap-анализ 2-3 регионов."""

    @extend_schema(
        parameters=[P_YEAR, P_OKATO_MULTI],
        responses=CompareRowSerializer(many=True),
        summary="Сравнение регионов (gap-анализ)",
    )
    def get(self, request: Request) -> Response:
        year, err = _parse_year(request)
        if err is not None:
            return err
        assert year is not None
        okatos = request.query_params.getlist("okato")
        if not COMPARE_MIN <= len(okatos) <= COMPARE_MAX:
            return Response(
                {"detail": f"нужно от {COMPARE_MIN} до {COMPARE_MAX} параметров 'okato'"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        data = queries.compare(okatos, year)
        log.info("compare", stage="api", okatos=okatos, year=year, rows=len(data))
        return Response(CompareRowSerializer(data, many=True).data)
