"""Служебные эндпойнты состояния приложения.

- `/healthz` (liveness) — процесс поднят и отвечает; без обращения к зависимостям.
  Используется оркестратором/хостингом для решения о перезапуске инстанса.
- `/readyz` (readiness) — приложение готово обслуживать запросы: проверяется доступность
  критичных зависимостей (PostgreSQL — операционные данные, DuckDB — аналитика).
  Возвращает 503, если хотя бы одна зависимость недоступна.

Оба эндпойнта открыты (без аутентификации), возвращают компактный JSON и не пишут аудит:
их назначение — health-пробы балансировщика и мониторинга.
"""

from __future__ import annotations

import duckdb
from django.conf import settings
from django.db import connection
from django.http import HttpRequest, JsonResponse


def healthz(_request: HttpRequest) -> JsonResponse:
    """Liveness-проба: приложение запущено и обрабатывает запросы."""
    return JsonResponse({"status": "ok"})


def readyz(_request: HttpRequest) -> JsonResponse:
    """Readiness-проба: критичные зависимости (PostgreSQL и DuckDB) доступны."""
    checks: dict[str, str] = {}
    ready = True

    # PostgreSQL (OLTP): простой запрос подтверждает живое соединение.
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        checks["database"] = "ok"
    except Exception:  # noqa: BLE001 — для health-пробы любая ошибка означает «не готов»
        checks["database"] = "error"
        ready = False

    # DuckDB (OLAP, только чтение): открываем витрину и выполняет тривиальный запрос.
    try:
        duck = duckdb.connect(str(settings.DUCKDB_PATH), read_only=True)
        try:
            duck.execute("SELECT 1").fetchone()
        finally:
            duck.close()
        checks["duckdb"] = "ok"
    except Exception:  # noqa: BLE001 — для health-пробы любая ошибка означает «не готов»
        checks["duckdb"] = "error"
        ready = False

    return JsonResponse(
        {"status": "ready" if ready else "not_ready", "checks": checks},
        status=200 if ready else 503,
    )
