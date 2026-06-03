"""Представления ядра. Сейчас — только healthcheck; контент-страницы — Ф7, API — Ф6."""

from django.http import HttpRequest, JsonResponse


def healthz(request: HttpRequest) -> JsonResponse:
    """Проверка живости: приложение поднялось и отвечает."""
    return JsonResponse({"status": "ok", "service": "regionlens"})
