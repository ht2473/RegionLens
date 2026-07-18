"""DRF-эндпойнты ядра: read-only чтение предрассчитанной аналитики из DuckDB.

Тонкий слой контроллера: валидация query-параметров → вызов core.queries → Response.
Вся работа с хранилищем — в core.queries (контракты раньше кода). Отклик
быстрый: читается уже посчитанное, без вычислений на лету (цель <200 мс). Каждый
эндпойнт декорирован @extend_schema — это даёт типизированную OpenAPI-схему и Swagger.
"""

from __future__ import annotations

from django.urls import reverse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from pipeline.logging_setup import log

from .. import queries
from ..serializers import (
    AnomalySerializer,
    BetaConvergenceRowSerializer,
    ClusterProfileRowSerializer,
    CompareRowSerializer,
    CorrelationRowSerializer,
    CustomIndexRowSerializer,
    DataQualityRowSerializer,
    DecompositionRowSerializer,
    DispersionRowSerializer,
    GeoLayerPointSerializer,
    IndexDispersionRowSerializer,
    IndexRowSerializer,
    MetricCatalogRowSerializer,
    MetricSerializer,
    MetricSeriesPointSerializer,
    MetricValuePointSerializer,
    ModelPredictionSerializer,
    MoranGlobalSerializer,
    MoranLocalRowSerializer,
    RankRobustnessRowSerializer,
    RankStabilityRowSerializer,
    RegionDashboardSerializer,
    RegionSerializer,
    RegionTwinSerializer,
    RegionVsTypeSerializer,
    ScenarioSerializer,
    SchemeAgreementRowSerializer,
    SiteSearchSerializer,
    TransitionSerializer,
    TypologyExplainSerializer,
    TypologyRowSerializer,
)

GEO_MEASURES = ("cluster", "index")
INDEX_SCHEMES = ("equal", "pca", "expert")
COMPARE_MIN, COMPARE_MAX = 2, 3
ANOMALY_KINDS = ("spatial", "structural_break", "methodology_change")

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


class RegionTwins(APIView):
    """GET /api/regions/<okato>/twins/?year=<int> — статистические двойники региона.

    top-N ближайших по косинусной близости профилей z_value за год (предрасчёт). Это
    сходство профиля показателей, НЕ причинность и НЕ прогноз. Пустой список — если у
    региона нет двойников за указанный год (например, год вне окна анализа).
    """

    @extend_schema(
        operation_id="region_twins",
        parameters=[P_YEAR],
        responses=RegionTwinSerializer(many=True),
        summary="Статистические двойники региона на год",
    )
    def get(self, request: Request, okato: str) -> Response:
        year, err = _parse_year(request)
        if err is not None:
            return err
        assert year is not None
        data = queries.region_twins(okato, year)
        log.info("region_twins", stage="api", okato=okato, year=year, rows=len(data))
        return Response(RegionTwinSerializer(data, many=True).data)


class RegionVsType(APIView):
    """GET /api/regions/<okato>/vs-type/?year=<int> — регион против своего типа.

    По каждой метрике ядра — разрыв z-оценки региона и центроида его типа (регион − тип),
    отсортированный по величине отличия, плюс типичность (удалённость от центра типа и
    позиция среди членов типа). 404 — если у региона нет кластера за указанный год.
    """

    @extend_schema(
        operation_id="region_vs_type",
        parameters=[P_YEAR],
        responses=RegionVsTypeSerializer,
        summary="Регион против своего типа на год",
    )
    def get(self, request: Request, okato: str) -> Response:
        year, err = _parse_year(request)
        if err is not None:
            return err
        assert year is not None
        data = queries.region_vs_type(okato, year)
        if data is None:
            return Response(
                {"detail": "нет типологии для региона за указанный год"},
                status=status.HTTP_404_NOT_FOUND,
            )
        log.info("region_vs_type", stage="api", okato=okato, year=year, rows=len(data["metrics"]))
        return Response(RegionVsTypeSerializer(data).data)


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


class RankRobustness(APIView):
    """GET /api/index/robustness/?year=<int> — коридор ранга по схемам весов на год.

    Для каждого региона — лучшая и худшая позиция среди схем весов (равные/PCA/экспертные)
    и ширина коридора. Делает видимой зависимость места региона от произвольного выбора весов
    (научное ядро «прозрачного индекса»). Описание данных, не пересчёт.
    """

    @extend_schema(
        parameters=[P_YEAR],
        responses=RankRobustnessRowSerializer(many=True),
        summary="Коридор ранга по схемам весов",
    )
    def get(self, request: Request) -> Response:
        year, err = _parse_year(request)
        if err is not None:
            return err
        assert year is not None
        data = queries.rank_robustness_list(year)
        log.info("rank_robustness", stage="api", year=year, rows=len(data))
        return Response(RankRobustnessRowSerializer(data, many=True).data)


class SchemeAgreement(APIView):
    """GET /api/index/scheme-agreement/ — согласованность рейтингов между схемами весов по годам.

    Для каждой пары схем (равные/PCA/экспертные) и года — ранговая корреляция Спирмена их
    рейтингов. Сводно показывает, насколько порядок регионов зависит от выбора весов и как это
    менялось во времени. Питает тренд согласованности в лаборатории индекса. Описание данных.
    """

    @extend_schema(
        responses=SchemeAgreementRowSerializer(many=True),
        summary="Согласованность схем весов по годам",
    )
    def get(self, request: Request) -> Response:
        data = queries.scheme_agreement_list()
        log.info("scheme_agreement", stage="api", rows=len(data))
        return Response(SchemeAgreementRowSerializer(data, many=True).data)


class IndexDispersion(APIView):
    """GET /api/index/dispersion/ — межрегиональный разброс индекса по годам и схемам.

    Меры σ-сходимости/неравенства композитного индекса (cv, gini, p90/p10, std) по (схема, год).
    Падение cv во времени — признак сближения регионов; рост — расхождения. Питает страницу
    конвергенции. Описание данных, не пересчёт.
    """

    @extend_schema(
        responses=IndexDispersionRowSerializer(many=True),
        summary="Разброс индекса по годам (σ-сходимость)",
    )
    def get(self, request: Request) -> Response:
        data = queries.index_dispersion_list()
        log.info("index_dispersion", stage="api", rows=len(data))
        return Response(IndexDispersionRowSerializer(data, many=True).data)


class BetaConvergence(APIView):
    """GET /api/index/beta/ — β-сходимость индекса по схемам весов.

    Для каждой схемы — наклон регрессии роста индекса на стартовый уровень (beta<0 — изначально
    отстающие регионы догоняли), период, корреляция и R². Индекс относительный, поэтому это
    мобильность/возврат к среднему, не абсолютный рост. Описание данных, не прогноз.
    """

    @extend_schema(
        responses=BetaConvergenceRowSerializer(many=True),
        summary="β-сходимость индекса по схемам весов",
    )
    def get(self, request: Request) -> Response:
        data = queries.beta_convergence_list()
        log.info("beta_convergence", stage="api", rows=len(data))
        return Response(BetaConvergenceRowSerializer(data, many=True).data)


class MoranGlobal(APIView):
    """GET /api/spatial/moran/?year=<int>&scheme=equal|pca|expert — глобальный Moran's I.

    Пространственная автокорреляция индекса развития: похожи ли соседние регионы. morans_i>0 —
    кластеризация (богатые рядом с богатыми и т. п.); значимость — перестановочным тестом.
    404, если пространственная стадия ещё не посчитана (нет таблицы/строки за год).
    """

    @extend_schema(
        operation_id="moran_global",
        parameters=[P_YEAR, P_SCHEME],
        responses=MoranGlobalSerializer,
        summary="Глобальный Moran's I индекса на год",
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
        data = queries.moran_global(year, scheme)
        if data is None:
            return Response(
                {"detail": "пространственная статистика не посчитана за указанный год/схему"},
                status=status.HTTP_404_NOT_FOUND,
            )
        log.info("moran_global", stage="api", year=year, scheme=scheme)
        return Response(MoranGlobalSerializer(data).data)


class MoranLocal(APIView):
    """GET /api/spatial/lisa/?year=<int>&scheme=equal|pca|expert — локальный LISA по регионам.

    По каждому региону — тип пространственного кластера (HH/LL — регион и соседи вместе высоко/
    низко; HL/LH — пространственные выбросы; ns — незначимо) для карты LISA. Read-only.
    """

    @extend_schema(
        operation_id="moran_local",
        parameters=[P_YEAR, P_SCHEME],
        responses=MoranLocalRowSerializer(many=True),
        summary="Локальный LISA по регионам на год",
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
        data = queries.moran_local(year, scheme)
        log.info("moran_local", stage="api", year=year, scheme=scheme, rows=len(data))
        return Response(MoranLocalRowSerializer(data, many=True).data)


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


class ModelPredict(APIView):
    """GET /api/models/predict/?okato=&year= — применить обученные модели к профилю региона.

    Интерактивная демонстрация ML-сервиса: сохранённые модели (классификатор типологии +
    детектор аномалий) загружаются из файлов и применяются к готовому профилю выбранного
    региона за год. Возвращает предсказанный тип и оценку нетипичности. Это применение
    модели к профилю, НЕ прогноз будущего и НЕ причинность.
    """

    @extend_schema(
        operation_id="models_predict",
        parameters=[
            P_YEAR,
            OpenApiParameter("okato", OpenApiTypes.STR, required=True, description="ОКАТО региона"),
        ],
        responses=ModelPredictionSerializer,
        summary="Применение ML-моделей к профилю региона",
    )
    def get(self, request: Request) -> Response:
        year, err = _parse_year(request)
        if err is not None:
            return err
        assert year is not None
        okato = request.query_params.get("okato")
        if not okato:
            return Response(
                {"detail": "параметр 'okato' обязателен"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        data = queries.model_predict_region(okato, year)
        if data is None:
            return Response(
                {"detail": "нет полного профиля региона за указанный год"},
                status=status.HTTP_404_NOT_FOUND,
            )
        log.info("models_predict", stage="api", okato=okato, year=year)
        return Response(ModelPredictionSerializer(data).data)


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


class Anomalies(APIView):
    """GET /api/anomalies/?year=&okato=&kind= — аномалии и структурные сдвиги.

    Доступ: роль analyst и выше (расширенная аналитика). Возвращает пространственные
    выбросы, структурные сдвиги рядов и кандидаты смены методологии (A3) с необязательными
    фильтрами. Описательная диагностика, не утверждение о причинах. Пустой список — норма.
    """

    @extend_schema(
        operation_id="anomalies",
        parameters=[
            OpenApiParameter("year", OpenApiTypes.INT, description="Год (опц.)"),
            P_OKATO,
            OpenApiParameter(
                "kind", OpenApiTypes.STR, enum=list(ANOMALY_KINDS), description="Вид аномалии"
            ),
        ],
        responses=AnomalySerializer(many=True),
        summary="Аномалии и структурные сдвиги (analyst)",
    )
    def get(self, request: Request) -> Response:
        raw_year = request.query_params.get("year")
        year: int | None = None
        if raw_year:
            try:
                year = int(raw_year)
            except ValueError:
                return Response(
                    {"detail": "'year' должен быть целым числом"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        kind = request.query_params.get("kind") or None
        if kind is not None and kind not in ANOMALY_KINDS:
            return Response(
                {"detail": f"'kind' должен быть одним из {', '.join(ANOMALY_KINDS)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        okato = request.query_params.get("okato") or None
        data = queries.anomalies_list(year=year, okato=okato, kind=kind)
        log.info("anomalies", stage="api", year=year, okato=okato, kind=kind, rows=len(data))
        return Response(AnomalySerializer(data, many=True).data)


class Dispersion(APIView):
    """GET /api/dispersion/?metric_id=&year=&from=&to= — межрегиональный разброс/неравенство.

    Описательные статистики разброса значений по регионам на (метрику, год): число регионов,
    среднее, медиана, std, P10/P90, IQR, размах, коэффициент вариации и отношение P90/P10
    (последние два — лишь для величин со шкалой отношений). Все фильтры необязательны; ряд по
    одной метрике за годы показывает, расширяется ли разрыв. Это описание, не прогноз.
    """

    @extend_schema(
        operation_id="dispersion",
        parameters=[
            OpenApiParameter("metric_id", OpenApiTypes.INT, description="Метрика (опц.)"),
            OpenApiParameter("year", OpenApiTypes.INT, description="Год (опц.)"),
            P_FROM,
            P_TO,
        ],
        responses=DispersionRowSerializer(many=True),
        summary="Разброс/неравенство регионов",
    )
    def get(self, request: Request) -> Response:
        try:
            metric_id = _optional_int(request.query_params.get("metric_id"))
            year = _optional_int(request.query_params.get("year"))
            year_from = _optional_int(request.query_params.get("from"))
            year_to = _optional_int(request.query_params.get("to"))
        except ValueError:
            return Response(
                {"detail": "числовые параметры (metric_id, year, from, to) должны быть целыми"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        data = queries.dispersion_list(
            metric_id=metric_id, year=year, year_from=year_from, year_to=year_to
        )
        log.info("dispersion", stage="api", metric_id=metric_id, year=year, rows=len(data))
        return Response(DispersionRowSerializer(data, many=True).data)


class RankStability(APIView):
    """GET /api/rank-stability/?scheme=equal|pca|expert — волатильность ранга регионов.

    Для выбранной схемы весов (по умолчанию equal): по региону за окно — средний ранг,
    разброс ранга (std), диапазон и средний модуль годового изменения ранга. Отсортировано
    от самых стабильных к самым «дёрганным». Это описание, не прогноз.
    """

    @extend_schema(
        operation_id="rank_stability",
        parameters=[P_SCHEME],
        responses=RankStabilityRowSerializer(many=True),
        summary="Стабильность рейтинга регионов",
    )
    def get(self, request: Request) -> Response:
        scheme = request.query_params.get("scheme", queries.MAP_INDEX_SCHEME)
        if scheme not in INDEX_SCHEMES:
            return Response(
                {"detail": f"'scheme' должна быть одной из {', '.join(INDEX_SCHEMES)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        data = queries.rank_stability_list(scheme=scheme)
        log.info("rank_stability", stage="api", scheme=scheme, rows=len(data))
        return Response(RankStabilityRowSerializer(data, many=True).data)


class Correlations(APIView):
    """GET /api/correlations/?year=&metric_id=&limit= — парные корреляции метрик (analyst-only).

    Описание совместного движения метрик по регионам за год (по умолчанию последний),
    отсортировано от сильнейших связей к слабым. metric_id — связи конкретной метрики (в любой
    позиции пары). Это описательная мера: корреляция ≠ причинность, и это не прогноз.
    """

    @extend_schema(
        operation_id="correlations",
        parameters=[
            P_YEAR,
            OpenApiParameter(
                "metric_id", OpenApiTypes.INT, description="Связи этой метрики (опц.)"
            ),
            OpenApiParameter("limit", OpenApiTypes.INT, description="Ограничить число пар (опц.)"),
        ],
        responses=CorrelationRowSerializer(many=True),
        summary="Корреляции метрик",
    )
    def get(self, request: Request) -> Response:
        try:
            year = _optional_int(request.query_params.get("year"))
            metric_id = _optional_int(request.query_params.get("metric_id"))
            limit = _optional_int(request.query_params.get("limit"))
        except ValueError:
            return Response(
                {"detail": "числовые параметры (year, metric_id, limit) должны быть целыми"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        data = queries.correlations_list(year=year, metric_id=metric_id, limit=limit)
        log.info("correlations", stage="api", year=year, metric_id=metric_id, rows=len(data))
        return Response(CorrelationRowSerializer(data, many=True).data)


class CustomIndex(APIView):
    """GET /api/index/custom/?year=&w_economy=&w_income=&… — кастомный рейтинг по своим весам.

    Пользователь задаёт веса шести доменов; индекс пересобирается как взвешенная сумма
    доменных баллов (баллы не зависят от схемы весов). Возвращает рейтинг на год (по умолчанию
    последний) с рангом и сдвигом относительно равных весов. Аналитический инструмент.
    """

    @extend_schema(
        operation_id="custom_index",
        parameters=[
            P_YEAR,
            *[
                OpenApiParameter(
                    f"w_{domain}", OpenApiTypes.NUMBER, description=f"Вес домена «{domain}» (≥0)"
                )
                for domain in queries.INDEX_DOMAINS
            ],
        ],
        responses=CustomIndexRowSerializer(many=True),
        summary="Кастомный индекс по своим весам",
    )
    def get(self, request: Request) -> Response:
        try:
            year = _optional_int(request.query_params.get("year"))
            weights = {
                domain: float(request.query_params.get(f"w_{domain}") or 0.0)
                for domain in queries.INDEX_DOMAINS
            }
        except ValueError:
            return Response(
                {"detail": "year должен быть целым, веса w_* — числами"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        resolved_year = year if year is not None else queries.latest_index_year()
        if resolved_year is None:
            return Response([])
        data = queries.custom_index_ranking(resolved_year, weights)
        log.info("custom_index", stage="api", year=resolved_year, rows=len(data))
        return Response(CustomIndexRowSerializer(data, many=True).data)


class IndexScenario(APIView):
    """GET /api/index/scenario/?year=&okato=&p_economy=&… — сценарий «что если» для региона.

    Параметры p_<domain> — целевые перцентили доменов (0–100). Возвращает базовое и сценарное
    место региона среди регионов года и текущие перцентили по доменам. Без p_* — текущее
    состояние (baseline == scenario). Аналитический инструмент планирования.
    """

    @extend_schema(
        operation_id="index_scenario",
        parameters=[
            P_YEAR,
            OpenApiParameter("okato", OpenApiTypes.STR, required=True, description="ОКАТО региона"),
            *[
                OpenApiParameter(
                    f"p_{domain}",
                    OpenApiTypes.NUMBER,
                    description=f"Целевой перцентиль домена «{domain}» (0–100)",
                )
                for domain in queries.INDEX_DOMAINS
            ],
        ],
        responses=ScenarioSerializer,
        summary="Сценарий развития региона (what-if)",
    )
    def get(self, request: Request) -> Response:
        okato = request.query_params.get("okato")
        if not okato:
            return Response({"detail": "нужен параметр okato"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            year = _optional_int(request.query_params.get("year"))
            overrides = {
                domain: float(raw)
                for domain in queries.INDEX_DOMAINS
                if (raw := request.query_params.get(f"p_{domain}")) not in (None, "")
            }
        except ValueError:
            return Response(
                {"detail": "year должен быть целым, перцентили p_* — числами"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        resolved_year = year if year is not None else queries.latest_index_year()
        if resolved_year is None:
            return Response({"detail": "нет данных индекса"}, status=status.HTTP_404_NOT_FOUND)
        data = queries.scenario_ranking(resolved_year, okato, overrides)
        if data is None:
            return Response(
                {"detail": "регион не найден за выбранный год"},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(ScenarioSerializer(data).data)


class Decomposition(APIView):
    """GET /api/decomposition/?okato=&scheme=&year= — вклад доменов в изменение индекса региона.

    Для региона и схемы весов (по умолчанию equal): по годам — на какой домен пришёлся прирост
    или спад индекса (вклады в сумме дают годовое изменение). year — конкретный год, иначе все
    годы. Сортировка по году и |вкладу|. Описательное разложение индекса, не прогноз.
    """

    @extend_schema(
        operation_id="decomposition",
        parameters=[P_OKATO, P_SCHEME, P_YEAR],
        responses=DecompositionRowSerializer(many=True),
        summary="Декомпозиция изменения индекса",
    )
    def get(self, request: Request) -> Response:
        okato = request.query_params.get("okato")
        if not okato:
            return Response(
                {"detail": "параметр okato обязателен"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        scheme = request.query_params.get("scheme", queries.MAP_INDEX_SCHEME)
        if scheme not in INDEX_SCHEMES:
            return Response(
                {"detail": f"'scheme' должна быть одной из {', '.join(INDEX_SCHEMES)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            year = _optional_int(request.query_params.get("year"))
        except ValueError:
            return Response(
                {"detail": "year должен быть целым"}, status=status.HTTP_400_BAD_REQUEST
            )
        data = queries.decomposition_list(okato=okato, scheme=scheme, year=year)
        log.info(
            "decomposition", stage="api", okato=okato, scheme=scheme, year=year, rows=len(data)
        )
        return Response(DecompositionRowSerializer(data, many=True).data)


class DataQuality(APIView):
    """GET /api/data-quality/?metric_id=&year=&from=&to= — полнота/импутации сетки на метрику-год.

    Описательная сводка качества аналитической матрицы: число регионов в группе, сколько ячеек с
    непустым сырьём (completeness_raw — доступность источника по году) и сколько достроено
    (impute_share — доля импутаций гармонизированной сетки). Для absolute-метрик две полноты
    расходятся (гармонизация делит на население). coverage — оконное покрытие сырья. Все фильтры
    необязательны; ряд по годам показывает динамику полноты. Это описание, не прогноз.
    """

    @extend_schema(
        operation_id="data_quality",
        parameters=[
            OpenApiParameter("metric_id", OpenApiTypes.INT, description="Метрика (опц.)"),
            OpenApiParameter("year", OpenApiTypes.INT, description="Год (опц.)"),
            P_FROM,
            P_TO,
        ],
        responses=DataQualityRowSerializer(many=True),
        summary="Качество данных (полнота/импутации)",
    )
    def get(self, request: Request) -> Response:
        try:
            metric_id = _optional_int(request.query_params.get("metric_id"))
            year = _optional_int(request.query_params.get("year"))
            year_from = _optional_int(request.query_params.get("from"))
            year_to = _optional_int(request.query_params.get("to"))
        except ValueError:
            return Response(
                {"detail": "числовые параметры (metric_id, year, from, to) должны быть целыми"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        data = queries.data_quality_list(
            metric_id=metric_id, year=year, year_from=year_from, year_to=year_to
        )
        log.info("data_quality", stage="api", metric_id=metric_id, year=year, rows=len(data))
        return Response(DataQualityRowSerializer(data, many=True).data)


class MetricCatalog(APIView):
    """GET /api/metric-catalog/?tier=&domain=&search=&limit= — каталог метрик с тирингом.

    Справочник того, что доступно для анализа: каждая метрика отнесена к тиру core (ядро индекса) /
    extended (вне ядра, но пригодна для explore) / sparse (разрежена) и снабжена профилем (домен,
    тип, покрытие, годовой охват по сырью). Основа explore-режима. Фильтры опциональны; limit
    ограничивает выдачу (каталог большой). Описание данных, не пересчёт аналитики.
    """

    @extend_schema(
        operation_id="metric_catalog",
        parameters=[
            OpenApiParameter("tier", OpenApiTypes.STR, description="core / extended / sparse"),
            OpenApiParameter("domain", OpenApiTypes.STR, description="Домен (опц.)"),
            OpenApiParameter("search", OpenApiTypes.STR, description="Поиск по имени метрики"),
            OpenApiParameter("metric_id", OpenApiTypes.INT, description="Одна метрика (опц.)"),
            OpenApiParameter("limit", OpenApiTypes.INT, description="Лимит выдачи (1..1000)"),
        ],
        responses=MetricCatalogRowSerializer(many=True),
        summary="Каталог метрик (тиринг и профиль)",
    )
    def get(self, request: Request) -> Response:
        tier = request.query_params.get("tier") or None
        domain = request.query_params.get("domain") or None
        search = request.query_params.get("search") or None
        metric_id_raw = request.query_params.get("metric_id")
        try:
            limit = int(request.query_params.get("limit", 200))
            metric_id = int(metric_id_raw) if metric_id_raw else None
        except ValueError:
            return Response(
                {"detail": "limit и metric_id должны быть целыми числами"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        limit = max(1, min(limit, 1000))
        data = queries.metric_catalog_list(
            tier=tier, domain=domain, search=search, metric_id=metric_id, limit=limit
        )
        log.info("metric_catalog", stage="api", tier=tier, domain=domain, rows=len(data))
        return Response(MetricCatalogRowSerializer(data, many=True).data)


class MetricValues(APIView):
    """GET /api/metric-values/?metric_id=&year= — значения метрики по регионам за год.

    Поперечный срез произвольной метрики каталога: для выбранного года значения по всем
    включённым регионам (отсортированы по убыванию). Ядро explore-режима. Описание данных
    (read-only из fact_region), не пересчёт аналитики.
    """

    @extend_schema(
        operation_id="metric_values",
        parameters=[
            OpenApiParameter("metric_id", OpenApiTypes.INT, required=True),
            OpenApiParameter("year", OpenApiTypes.INT, required=True),
        ],
        responses=MetricValuePointSerializer(many=True),
        summary="Значения метрики по регионам за год",
    )
    def get(self, request: Request) -> Response:
        try:
            metric_id = int(request.query_params["metric_id"])
            year = int(request.query_params["year"])
        except (KeyError, ValueError):
            return Response(
                {"detail": "Нужны числовые параметры metric_id и year"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        data = queries.metric_values(metric_id, year)
        log.info("metric_values", stage="api", metric_id=metric_id, year=year, rows=len(data))
        return Response(MetricValuePointSerializer(data, many=True).data)


# Статические страницы сайта для глобального поиска (заголовок → имя маршрута).
SEARCH_PAGES: list[tuple[str, str]] = [
    ("Главная", "home"),
    ("Карта", "map"),
    ("Показатели", "explore"),
    ("Регионы", "regions"),
    ("Рейтинг регионов", "rankings"),
    ("Лаборатория индекса", "index_lab"),
    ("Конвергенция", "convergence"),
    ("Неравенство регионов", "dispersion_page"),
    ("Типология регионов", "typology"),
    ("Сравнение регионов", "compare"),
    ("Аномалии", "anomalies_page"),
    ("Корреляции", "correlations_page"),
    ("Методология", "methodology"),
    ("Данные", "data"),
    ("Качество данных", "data_quality_page"),
    ("Справка", "help"),
    ("Обратная связь", "feedback"),
]


class SiteSearch(APIView):
    """GET /api/search/?q=<str> — глобальный поиск: регионы, показатели, страницы.

    Лёгкая выдача для поля в шапке. Регионы/показатели — из DuckDB (queries.search),
    страницы — статический список (фильтр по подстроке заголовка). Минимум запроса —
    2 символа: на более коротких возвращается пустая выдача без обращения к хранилищу.
    """

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "q", OpenApiTypes.STR, description="Поисковый запрос (минимум 2 символа)."
            ),
        ],
        responses=SiteSearchSerializer,
        summary="Глобальный поиск по сайту",
    )
    def get(self, request: Request) -> Response:
        query = (request.query_params.get("q") or "").strip()
        if len(query) < 2:
            return Response({"query": query, "regions": [], "metrics": [], "pages": []})
        found = queries.search(query, limit=6)
        ql = query.lower()
        pages = [
            {"title": title, "url": reverse(name)}
            for title, name in SEARCH_PAGES
            if ql in title.lower()
        ][:6]
        payload = {
            "query": query,
            "regions": found["regions"],
            "metrics": found["metrics"],
            "pages": pages,
        }
        log.info(
            "site_search",
            stage="api",
            q=query,
            regions=len(found["regions"]),
            metrics=len(found["metrics"]),
            pages=len(pages),
        )
        return Response(SiteSearchSerializer(payload).data)
