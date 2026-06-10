"""Корневая маршрутизация проекта. Расширяется в Ф6 (API) / Ф7 (страницы) / Ф10."""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("core.urls")),
]

# В DEBUG отдаём сохранённые файлы экспорта (MEDIA) самим Django; в проде — веб-сервер (Ф12).
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
