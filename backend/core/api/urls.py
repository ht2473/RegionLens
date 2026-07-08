"""Маршруты API ядра. Подключаются под префиксом /api/ из core.urls.

Аналитические эндпойнты read-only (DuckDB) + OpenAPI-схема и Swagger (drf-spectacular).
Порядок важен: статический `typology/profile/` объявлен раньше `typology/<okato>/explain/`,
чтобы «profile» не был перехвачен как okato.
"""

from django.urls import path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from . import endpoints

app_name = "api"

urlpatterns = [
    # OpenAPI / Swagger
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="api:schema"), name="swagger-ui"),
    # Карта / каталоги
    path("geo/layer/", endpoints.GeoLayer.as_view(), name="geo-layer"),
    path("regions/", endpoints.RegionList.as_view(), name="regions"),
    path("search/", endpoints.SiteSearch.as_view(), name="search"),
    path("regions/<str:okato>/", endpoints.RegionDashboard.as_view(), name="region-dashboard"),
    path(
        "regions/<str:okato>/twins/",
        endpoints.RegionTwins.as_view(),
        name="region-twins",
    ),
    path("metrics/", endpoints.MetricList.as_view(), name="metrics"),
    path(
        "metrics/<int:metric_id>/series/",
        endpoints.MetricSeries.as_view(),
        name="metric-series",
    ),
    # Индекс / переходы
    path("index/", endpoints.IndexRanking.as_view(), name="index"),
    path("index/robustness/", endpoints.RankRobustness.as_view(), name="rank_robustness"),
    path(
        "index/scheme-agreement/",
        endpoints.SchemeAgreement.as_view(),
        name="scheme_agreement",
    ),
    path("index/dispersion/", endpoints.IndexDispersion.as_view(), name="index_dispersion"),
    path("index/beta/", endpoints.BetaConvergence.as_view(), name="beta_convergence"),
    path("transitions/", endpoints.Transitions.as_view(), name="transitions"),
    # Типология (profile — до <okato>/explain, чтобы не перехватился как okato)
    path("typology/", endpoints.Typology.as_view(), name="typology"),
    path("typology/profile/", endpoints.ClusterProfile.as_view(), name="typology-profile"),
    path(
        "typology/<str:okato>/explain/",
        endpoints.TypologyExplain.as_view(),
        name="typology-explain",
    ),
    # Сравнение
    path("compare/", endpoints.Compare.as_view(), name="compare"),
    # Аномалии и структурные сдвиги (доступ analyst)
    path("anomalies/", endpoints.Anomalies.as_view(), name="anomalies"),
    # Разброс/неравенство регионов на метрику-год
    path("dispersion/", endpoints.Dispersion.as_view(), name="dispersion"),
    # Стабильность рейтинга: волатильность ранга регионов по годам
    path("rank-stability/", endpoints.RankStability.as_view(), name="rank_stability"),
    # Парные корреляции метрик по регионам (доступ analyst)
    path("correlations/", endpoints.Correlations.as_view(), name="correlations"),
    # Кастомный индекс по пользовательским весам доменов
    path("index/custom/", endpoints.CustomIndex.as_view(), name="custom_index"),
    # Сценарий развития региона (what-if по перцентилям доменов)
    path("index/scenario/", endpoints.IndexScenario.as_view(), name="index_scenario"),
    # Вклад доменов в годовое изменение индекса региона
    path("decomposition/", endpoints.Decomposition.as_view(), name="decomposition"),
    # Качество данных: полнота/импутации аналитической сетки на метрику-год
    path("data-quality/", endpoints.DataQuality.as_view(), name="data_quality"),
    # Каталог метрик: тиринг (core/extended/sparse) и профиль всего справочника
    path("metric-catalog/", endpoints.MetricCatalog.as_view(), name="metric_catalog"),
    # Значения произвольной метрики по регионам за год (explore)
    path("metric-values/", endpoints.MetricValues.as_view(), name="metric_values"),
]
