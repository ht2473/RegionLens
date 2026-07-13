"""Обновление витрины: приём выгрузки, staging-сборка, проверка, атомарная подмена.

Поток обновления данных (ручные parquet-выгрузки портала «Если быть точным»):
  1) ``ingest_incoming`` — проверить схему входного parquet (14 канонических колонок),
     скопировать его в каталог сырья и перенацелить реестр источников
     (``config/sources.yaml``) на новое версионированное имя файла;
  2) ``build_staging`` — собрать ВЕСЬ конвейер в отдельный staging-файл DuckDB;
     боевая витрина в это время не затрагивается и продолжает обслуживать чтение;
  3) ``validate_staging`` — независимая проверка результата: ключевые таблицы непусты,
     свежесть данных (MAX(year)) не откатилась относительно текущей витрины;
  4) ``swap_store`` — резервная копия текущей витрины и атомарная подмена файлом
     staging (``os.replace``): у читателей нет «окна» без файла, а уже открытые
     read-only соединения продолжают видеть старый inode до переподключения
     (горячее переподключение реализовано в ``core.duck``).

Модуль принадлежит «миру конвейера» (он пишет DuckDB); приложение вызывает его только
через management-команду ``refresh_data`` и само витрину никогда не изменяет.
"""

from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path

import duckdb

from pipeline.logging_setup import log

#: Таблицы, без которых витрина не имеет смысла: справочник регионов, факт-таблица
#: показателей и композитный индекс. Их непустота — минимальный смысловой критерий
#: успешной сборки (полноту по стадиям гарантирует сам оркестратор: он сверяет
#: contract-таблицы каждой стадии сразу после её выполнения).
REQUIRED_TABLES: tuple[str, ...] = ("region_dim", "fact_region", "dev_index")

#: Санитарный диапазон числа субъектов РФ в витрине. Значение вне диапазона означает
#: битую или чужую выгрузку, а не изменение административного деления.
REGIONS_RANGE: tuple[int, int] = (80, 100)


class RefreshError(RuntimeError):
    """Ошибка процедуры обновления: витрина остаётся нетронутой."""


def registered_source_path(sources_path: Path) -> Path:
    """Путь parquet-источника, на который сейчас указывает реестр источников.

    Реестр содержит ровно один источник (коллекция Росстата); при появлении второго
    процедуру приёма нужно расширить осознанно, поэтому неоднозначность — ошибка.
    """
    import yaml

    registry = yaml.safe_load(sources_path.read_text(encoding="utf-8"))
    sources = registry.get("sources") or []
    if len(sources) != 1:
        raise RefreshError(
            f"Ожидался ровно один источник в {sources_path}, найдено {len(sources)}: "
            "приём выгрузки нескольких источников требует явного расширения refresh."
        )
    return Path(sources[0]["path"])


def check_incoming_schema(incoming: Path) -> int:
    """Проверить, что входной parquet читается и содержит канонические колонки.

    Проверка через DuckDB без загрузки данных (``LIMIT 0``): дешёвая и не требует
    polars. Возвращает число строк файла — для журнала и итоговой сводки.
    """
    # Ленивый импорт: ingestion.base тянет polars, который в web-установке появляется
    # только вместе с extras конвейера — модуль refresh должен импортироваться и без него.
    from pipeline.ingestion.base import CANONICAL

    if not incoming.exists():
        raise RefreshError(f"Входной файл не найден: {incoming}")
    con = duckdb.connect(":memory:")
    try:
        try:
            described = con.execute(
                "DESCRIBE SELECT * FROM read_parquet(?) LIMIT 0", [str(incoming)]
            ).fetchall()
        except duckdb.Error as exc:  # битый/не-parquet файл
            raise RefreshError(f"Файл не читается как parquet: {incoming} ({exc})") from exc
        columns = {row[0] for row in described}
        missing = [c for c in CANONICAL if c not in columns]
        if missing:
            raise RefreshError(
                "Во входном parquet нет обязательных колонок канонической схемы: "
                + ", ".join(missing)
            )
        rows = con.execute("SELECT COUNT(*) FROM read_parquet(?)", [str(incoming)]).fetchone()
        return int(rows[0]) if rows else 0
    finally:
        con.close()


def ingest_incoming(incoming: Path, sources_path: Path, repo_root: Path) -> Path:
    """Принять выгрузку: скопировать в каталог сырья и перенацелить реестр источников.

    Имя файла сохраняется как есть — оно версионировано датой среза
    (``..._v20260313.parquet``), и терять эту информацию нельзя. Реестр правится
    точечной текстовой заменой значения ``path:`` — так сохраняются комментарии и
    настройки источника (``na_values`` и пр.), которые ``yaml.dump`` уничтожил бы.

    Возвращает абсолютный путь принятого файла в каталоге сырья.
    """
    rows = check_incoming_schema(incoming)
    registered_rel = registered_source_path(sources_path)
    raw_dir = repo_root / registered_rel.parent
    raw_dir.mkdir(parents=True, exist_ok=True)
    dest = raw_dir / incoming.name
    shutil.copy2(incoming, dest)

    if incoming.name != registered_rel.name:
        new_rel = (registered_rel.parent / incoming.name).as_posix()
        text = sources_path.read_text(encoding="utf-8")
        needle = f"path: {registered_rel.as_posix()}"
        if text.count(needle) != 1:
            raise RefreshError(
                f"Не удалось однозначно перенацелить реестр {sources_path}: "
                f"строка «{needle}» встречается {text.count(needle)} раз(а)."
            )
        sources_path.write_text(text.replace(needle, f"path: {new_rel}"), encoding="utf-8")

    log.info(
        "refresh_ingest",
        stage="refresh",
        incoming=str(incoming),
        dest=str(dest),
        rows=rows,
    )
    return dest


def build_staging(staging: Path, sources_path: Path) -> None:
    """Собрать весь конвейер в staging-файл DuckDB (боевая витрина не затрагивается).

    MLflow при обновлении отключён намеренно: это регулярная пересборка данных,
    а не эксперимент с моделями; на сервере трекинг-стек не разворачивается.
    """
    from pipeline.run_all import run_all

    staging.parent.mkdir(parents=True, exist_ok=True)
    if staging.exists():
        staging.unlink()  # незавершённая прошлая сборка не должна смешиваться с новой
    run_all(
        duckdb_path=str(staging),
        sources_path=str(sources_path),
        only=None,
        from_=None,
        log_mlflow=False,
    )


def _max_year(con: duckdb.DuckDBPyConnection) -> int | None:
    """MAX(year) из fact_region либо None, если таблицы нет/пуста (битая витрина)."""
    try:
        row = con.execute("SELECT MAX(year) FROM fact_region").fetchone()
    except duckdb.Error:
        return None
    return int(row[0]) if row and row[0] is not None else None


def validate_staging(staging: Path, current: Path | None) -> dict[str, object]:
    """Независимая проверка собранной витрины перед подменой боевой.

    Проверяются смысловые инварианты, которые сборка сама о себе знать не может:
    ключевые таблицы непусты, число регионов в санитарном диапазоне, а свежесть
    (MAX(year)) не откатилась относительно текущей витрины — защита от случайной
    подмены боевых данных более старым срезом.
    """
    con = duckdb.connect(str(staging), read_only=True)
    try:
        for table in REQUIRED_TABLES:
            try:
                row = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()  # noqa: S608
            except duckdb.Error as exc:
                raise RefreshError(f"В собранной витрине нет таблицы {table}: {exc}") from exc
            if not row or int(row[0]) == 0:
                raise RefreshError(f"Таблица {table} в собранной витрине пуста.")

        regions_row = con.execute("SELECT COUNT(*) FROM region_dim").fetchone()
        regions = int(regions_row[0]) if regions_row else 0
        lo, hi = REGIONS_RANGE
        if not (lo <= regions <= hi):
            raise RefreshError(
                f"Число регионов в собранной витрине подозрительно: {regions} "
                f"(ожидалось {lo}–{hi})."
            )

        new_year = _max_year(con)
        if new_year is None:
            raise RefreshError("В собранной витрине не определяется MAX(year) по fact_region.")
    finally:
        con.close()

    if current is not None and current.exists():
        prev_con = duckdb.connect(str(current), read_only=True)
        try:
            old_year = _max_year(prev_con)
        except duckdb.Error:
            old_year = None  # текущая витрина битая — подмена свежей допустима
        finally:
            prev_con.close()
        if old_year is not None and new_year < old_year:
            raise RefreshError(
                f"Свежесть откатилась: в собранной витрине MAX(year)={new_year}, "
                f"в текущей — {old_year}. Подмена отклонена."
            )

    summary: dict[str, object] = {"regions": regions, "max_year": new_year}
    log.info("refresh_validate", stage="refresh", **summary)
    return summary


def swap_store(staging: Path, target: Path, backups_dir: Path, keep: int = 3) -> Path | None:
    """Резервная копия текущей витрины и атомарная подмена файлом staging.

    Бэкап делается КОПИЕЙ (не переносом): между «убрали старый файл» и «положили
    новый» не возникает окна, когда витрины нет вовсе. Сама подмена — ``os.replace``:
    атомарна в пределах файловой системы; открытые read-only соединения читателей
    продолжают видеть прежний inode до переподключения. Хранится ``keep`` последних
    бэкапов, более старые удаляются.

    Возвращает путь созданного бэкапа (None, если боевой витрины ещё не было).
    """
    backups_dir.mkdir(parents=True, exist_ok=True)
    backup: Path | None = None
    if target.exists():
        # Метка с микросекундами: имена уникальны даже при подменах в одну секунду
        # (иначе copy2 молча перезаписал бы предыдущий бэкап), а лексикографический
        # порядок по-прежнему совпадает с хронологическим.
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        backup = backups_dir / f"regionlens_{stamp}.duckdb"
        shutil.copy2(target, backup)
    os.replace(staging, target)

    # Ротация: имена содержат сортируемую метку времени — лексикографический порядок
    # совпадает с хронологическим, свежие в конце.
    existing = sorted(backups_dir.glob("regionlens_*.duckdb"))
    for stale in existing[:-keep] if keep > 0 else existing:
        stale.unlink()

    log.info(
        "refresh_swap",
        stage="refresh",
        target=str(target),
        backup=str(backup) if backup else None,
        kept_backups=min(len(existing), keep),
    )
    return backup


def archive_processed(processed: Path) -> Path:
    """Убрать обработанную выгрузку в подкаталог ``processed/`` с меткой времени.

    Нужен режиму «каталога приёма» (systemd path-юнит срабатывает на появление
    ``*.parquet``): после успешного обновления файл перемещается, условие срабатывания
    гаснет, а история принятых выгрузок остаётся на диске.
    """
    archive_dir = processed.parent / "processed"
    archive_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    dest = archive_dir / f"{stamp}_{processed.name}"
    shutil.move(str(processed), dest)
    return dest
