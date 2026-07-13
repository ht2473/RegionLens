"""Read-only доступ приложения к аналитическому хранилищу DuckDB.

Архитектура «два мира»: DuckDB-файл пишет ТОЛЬКО офлайн-конвейер; приложение
открывает его строго read-only и лишь читает готовое. Соединение кэшируется на
процесс; под каждый запрос берётся отдельный курсор (``con.cursor()``) — это
потокобезопасный способ конкурентного чтения в многопоточном Django/gunicorn.

Горячее переподключение после обновления витрины. Команда refresh_data подменяет
файл атомарно (``os.replace``); чтобы работающие воркеры увидели новые данные без
рестарта, кэш соединения привязан к сигнатуре файла (inode, размер, mtime), и её
смена прозрачно переоткрывает витрину. Стоимость — один ``os.stat`` не чаще, чем
раз в ``_STAT_INTERVAL`` секунд на процесс. Сценарий «подмена под открытым
читателем» — Linux-семантика (боевая платформа): Windows такую замену запрещает на
уровне ОС, поэтому на dev-машине под Windows читателей на время подмены нужно
останавливать (команда сообщает об этом понятной ошибкой).

ВАЖНО про способ открытия. ``duckdb.connect(path)`` в python-клиенте кэширует
ИНСТАНС базы по пути: повторный connect к тому же пути присоединяется к уже
открытому инстансу со СТАРЫМ inode, и после подмены файла процесс навсегда видел бы
прежний срез (проверено эмпирически). Поэтому витрина открывается иначе: каждый раз
создаётся свежий in-memory инстанс (он в кэш не попадает) и файл подключается через
``ATTACH ... (READ_ONLY)`` — такое подключение читает файл заново даже при живых
старых соединениях. Курсор НЕ наследует выбранный каталог, поэтому ``q()`` выполняет
``USE store`` на каждом курсоре (микросекунды).
"""

from __future__ import annotations

import contextlib
import os
import threading
import time
from typing import Any

import duckdb
from django.conf import settings

from pipeline.logging_setup import log

#: Алиас, под которым витрина подключена к in-memory инстансу (см. докстринг модуля).
_STORE_ALIAS = "store"

#: Минимальный интервал (сек) между проверками сигнатуры файла витрины. Держит
#: накладные расходы на уровне «≤1 stat/сек на процесс»; после подмены файла воркер
#: увидит новые данные не позднее, чем через этот интервал.
_STAT_INTERVAL = 1.0

_lock = threading.Lock()
_con: duckdb.DuckDBPyConnection | None = None
_path: str | None = None
_signature: tuple[int, int, int] | None = None
_checked_at: float = 0.0


def _file_signature(path: str) -> tuple[int, int, int] | None:
    """Сигнатура файла витрины: (inode, размер, mtime_ns) либо None, если файла нет.

    ``os.replace`` на Linux создаёт новый inode, на Windows меняются mtime/размер —
    любая подмена меняет сигнатуру на обеих платформах.
    """
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_ino, st.st_size, st.st_mtime_ns)


def _open_store(path: str) -> duckdb.DuckDBPyConnection:
    """Открыть витрину свежим инстансом: memory-соединение + ATTACH (READ_ONLY).

    Путь экранируется удвоением одинарных кавычек (параметры в ATTACH не
    поддерживаются). Ошибка подключения (нет файла, битый файл) пробрасывается
    как duckdb-исключение — обработчик API вернёт 500, как и раньше.
    """
    con = duckdb.connect()
    escaped = path.replace("'", "''")
    con.execute(f"ATTACH '{escaped}' AS {_STORE_ALIAS} (READ_ONLY)")
    con.execute(f"USE {_STORE_ALIAS}")
    return con


def get_con() -> duckdb.DuckDBPyConnection:
    """Кэшированное read-only соединение с витриной (одно на процесс).

    Путь берётся из ``settings.DUCKDB_PATH`` (без хардкода); смена пути в настройках
    (тесты) или сигнатуры файла (обновление витрины) прозрачно переоткрывает
    соединение. Прежний объект намеренно НЕ закрывается явно: параллельные запросы
    могут ещё держать его курсоры — инстанс освободит сборщик мусора, когда
    последний курсор завершит работу.
    """
    global _con, _path, _signature, _checked_at
    with _lock:
        path = str(settings.DUCKDB_PATH)
        now = time.monotonic()
        if _con is not None and path == _path and (now - _checked_at) < _STAT_INTERVAL:
            return _con

        signature = _file_signature(path)
        _checked_at = now
        if _con is not None and path == _path and signature == _signature and signature is not None:
            return _con

        log.info(
            "duckdb_connect",
            stage="api",
            path=path,
            read_only=True,
            reload=_con is not None,
        )
        _con = _open_store(path)
        _path = path
        _signature = signature
        return _con


def q(sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
    """Выполнить параметризованный read-only SQL и вернуть список словарей.

    Под каждый запрос берётся отдельный курсор общего соединения — безопасно при
    конкурентных чтениях из разных потоков. Курсор не наследует выбранный каталог,
    поэтому витрина выбирается явно (``USE``) — неквалифицированные имена таблиц в
    SQL продолжают работать как раньше. Параметры передаются через placeholders
    (``?``), а не конкатенацией строк (защита от инъекций).
    """
    cur = get_con().cursor()
    try:
        cur.execute(f"USE {_STORE_ALIAS}")
        cur.execute(sql, params or [])
        columns = [d[0] for d in cur.description]
        return [dict(zip(columns, row, strict=True)) for row in cur.fetchall()]
    finally:
        cur.close()


def reset_connection() -> None:
    """Сбросить кэш соединения (тесты, переключение пути DuckDB, обновление витрины).

    В отличие от горячего переподключения в ``get_con`` (там прежний объект отдаётся
    сборщику мусора из-за возможных параллельных курсоров), здесь соединение
    закрывается ЯВНО: вызов административный, конкурентных курсоров в этот момент
    нет, а на Windows немедленное закрытие детерминированно освобождает файл —
    иначе подмена витрины ждала бы недетерминированного прохода GC.
    """
    global _con, _path, _signature, _checked_at
    with _lock:
        if _con is not None:
            # Соединение могло умереть раньше — это не мешает сбросу.
            with contextlib.suppress(duckdb.Error):
                _con.close()
        _con = None
        _path = None
        _signature = None
        _checked_at = 0.0
