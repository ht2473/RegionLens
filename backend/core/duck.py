"""Read-only доступ приложения к аналитическому хранилищу DuckDB.

Архитектура «два мира»: DuckDB-файл пишет ТОЛЬКО офлайн-конвейер;
приложение открывает его строго read-only и лишь читает готовое. Соединение
кэшируется на процесс (`@lru_cache`); под каждый запрос берётся отдельный курсор
(`con.cursor()`) — это потокобезопасный способ конкурентного чтения в многопоточном
Django/gunicorn (одно read-only соединение к файлу, изолированные курсоры на запрос).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import duckdb
from django.conf import settings

from pipeline.logging_setup import log


@lru_cache(maxsize=1)
def get_con() -> duckdb.DuckDBPyConnection:
    """Кэшированное read-only соединение с DuckDB (одно на процесс).

    Путь берётся из settings.DUCKDB_PATH (без хардкода). read_only=True безопасно
    для конкурентного чтения и гарантирует, что приложение не изменит хранилище.
    """
    path = str(settings.DUCKDB_PATH)
    log.info("duckdb_connect", stage="api", path=path, read_only=True)
    return duckdb.connect(path, read_only=True)


def q(sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
    """Выполнить параметризованный read-only SQL и вернуть список словарей.

    Под каждый запрос берётся отдельный курсор общего соединения — безопасно при
    конкурентных чтениях из разных потоков. Параметры передаются через placeholders
    (`?`), а не конкатенацией строк (защита от инъекций).
    """
    cur = get_con().cursor()
    try:
        cur.execute(sql, params or [])
        columns = [d[0] for d in cur.description]
        return [dict(zip(columns, row, strict=True)) for row in cur.fetchall()]
    finally:
        cur.close()


def reset_connection() -> None:
    """Сбросить кэш соединения (для тестов и переключения пути DuckDB)."""
    get_con.cache_clear()
