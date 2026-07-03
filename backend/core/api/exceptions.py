"""Единый обработчик исключений DRF: логирование + предсказуемое тело ответа.

Подключается через REST_FRAMEWORK["EXCEPTION_HANDLER"]. Известные DRF-исключения
(валидация, 404 и т.п.) проходят штатно, но логируются; всё необработанное (например,
ошибка чтения DuckDB) превращается в чистый 500 без утечки трейсбэка наружу, с записью
причины в лог (structlog) для разбора по логам сервера.
"""

from __future__ import annotations

from typing import Any

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler

from pipeline.logging_setup import log


def custom_exception_handler(exc: Exception, context: dict[str, Any]) -> Response:
    """Обработать исключение API: залогировать и вернуть предсказуемый ответ."""
    view = context.get("view")
    view_name = view.__class__.__name__ if view is not None else None
    response = exception_handler(exc, context)

    if response is None:
        log.error("api_unhandled_error", stage="api", view=view_name, error=repr(exc))
        return Response(
            {"detail": "внутренняя ошибка сервера"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    log.warning("api_error", stage="api", view=view_name, status=response.status_code)
    return response
