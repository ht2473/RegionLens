"""Корреляция запросов: сквозной идентификатор X-Request-ID (Фаза 2 — зрелость API).

Каждому HTTP-запросу присваивается request_id: берётся из входящего заголовка X-Request-ID
(если клиент/прокси его прислал) либо генерируется. Идентификатор связывается с
контекстом structlog (bind_contextvars) — и попадает во ВСЕ записи лога этого запроса
(см. merge_contextvars в logging_setup), а также возвращается в заголовке ответа X-Request-ID.
Это даёт сквозную трассировку «один запрос — один id» в логах и у клиента, без БД и состояния.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

import structlog
from django.http import HttpRequest, HttpResponse

#: Имя заголовка корреляции (общий де-факто стандарт).
REQUEST_ID_HEADER = "X-Request-ID"
#: Предел длины принимаемого извне id — отсекаем подозрительно длинные значения (header-инъекции).
_MAX_LEN = 200


class RequestIDMiddleware:
    """Присвоить запросу X-Request-ID, связать с логами и вернуть в ответе."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        incoming = request.headers.get(REQUEST_ID_HEADER, "").strip()
        # Принимаем только короткий безопасный id (буквы/цифры/-/_), иначе генерируем свой.
        request_id = incoming[:_MAX_LEN] if _is_safe(incoming) else uuid.uuid4().hex
        structlog.contextvars.bind_contextvars(request_id=request_id)
        try:
            response = self.get_response(request)
        finally:
            structlog.contextvars.clear_contextvars()
        response[REQUEST_ID_HEADER] = request_id
        return response


def _is_safe(value: str) -> bool:
    """Принимаемый извне id должен быть непустым, не длиннее предела и без управляющих символов."""
    return bool(value) and len(value) <= _MAX_LEN and all(c.isalnum() or c in "-_" for c in value)
