"""Корневая маршрутизация проекта: подключает API и страницы."""

from core.health import healthz, readyz
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.i18n import JavaScriptCatalog

urlpatterns = [
    path("admin/", admin.site.urls),
    # Служебные эндпойнты состояния (для хостинга/мониторинга; без аутентификации).
    path("healthz", healthz, name="healthz"),
    path("readyz", readyz, name="readyz"),
    # Метрики Prometheus (/metrics).
    path("", include("django_prometheus.urls")),
    # Стандартный маршрут django для смены языка (view set_language).
    path("i18n/", include("django.conf.urls.i18n")),
    # Каталог переводов для JavaScript (домен djangojs): предоставляет gettext() в JS.
    path("jsi18n/", JavaScriptCatalog.as_view(domain="djangojs"), name="javascript-catalog"),
    path("", include("core.urls")),
]

# В DEBUG отдаём сохранённые файлы экспорта (MEDIA) самим Django; в проде — веб-сервер.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
