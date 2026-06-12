"""Маршруты API ядра (Ф6). Подключаются под префиксом /api/ из core.urls.

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
]
