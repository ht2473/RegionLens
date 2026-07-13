"""Тесты обновления витрины: приём выгрузки, валидация, подмена, горячее переподключение.

Тяжёлая сборка конвейера здесь не запускается: проверяется именно логика процедуры
(``pipeline.refresh``) на миниатюрных DuckDB-файлах, а в сквозном тесте команды шаг
сборки подменяется записью готовой мини-витрины в staging. Это web-совместимые тесты —
им не нужны extras конвейера сверх duckdb/polars.
"""

from __future__ import annotations

import os
from io import StringIO
from pathlib import Path

import duckdb
import pytest
from core import duck
from django.core.management import CommandError, call_command

from pipeline import refresh

# --- Вспомогательные фабрики -----------------------------------------------------------


def make_store(path: Path, *, year: int = 2024, regions: int = 85, probe: int = 1) -> None:
    """Мини-витрина с таблицами, которые проверяет validate_staging.

    ``probe`` — маркерное значение для проверки, КАКОЙ именно файл видит читатель
    (тесты подмены и горячего переподключения различают версии витрины по нему).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    con = duckdb.connect(str(path))
    try:
        con.execute("CREATE TABLE region_dim (okato VARCHAR, region_name VARCHAR)")
        con.execute("CREATE TABLE fact_region (okato VARCHAR, year INTEGER)")
        con.execute("CREATE TABLE dev_index (okato VARCHAR, year INTEGER, score DOUBLE)")
        con.execute("CREATE TABLE probe (v INTEGER)")
        for i in range(regions):
            okato = f"{i:02d}000000"
            con.execute("INSERT INTO region_dim VALUES (?, ?)", [okato, f"Регион {i}"])
            con.execute("INSERT INTO fact_region VALUES (?, ?)", [okato, year])
        con.execute("INSERT INTO dev_index VALUES ('00000000', ?, 50.0)", [year])
        con.execute("INSERT INTO probe VALUES (?)", [probe])
    finally:
        con.close()


def make_parquet(path: Path, *, drop_columns: tuple[str, ...] = ()) -> None:
    """Parquet канонической схемы (14 колонок) с одной строкой-заглушкой.

    ``drop_columns`` исключает колонки — для проверки отбраковки неполной схемы.
    """
    from pipeline.ingestion.base import CANONICAL

    path.parent.mkdir(parents=True, exist_ok=True)
    cols = [c for c in CANONICAL if c not in drop_columns]

    def cell(c: str) -> str:
        if c == "year":
            return f"2024 AS {c}"
        if c == "indicator_value":
            return f"1.0 AS {c}"
        return f"'x' AS {c}"

    select = ", ".join(cell(c) for c in cols)
    con = duckdb.connect(":memory:")
    try:
        con.execute(f"COPY (SELECT {select}) TO '{path.as_posix()}' (FORMAT PARQUET)")  # noqa: S608
    finally:
        con.close()


def write_registry(path: Path, source_rel: str) -> None:
    """Реестр источников в формате боевого config/sources.yaml (с комментариями)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# Реестр источников данных. Каждый источник -> свой адаптер.\n"
        "sources:\n"
        "  - id: rosstat_collection_102\n"
        "    adapter: pipeline.ingestion.rosstat_collection.RosstatCollectionAdapter\n"
        f"    path: {source_rel}\n"
        '    license: "CC BY 4.0"\n'
        "    # Коды «нет данных» зануляем при чтении.\n"
        "    na_values: [-99999999, -77777777]\n",
        encoding="utf-8",
    )


def read_probe(path: Path) -> int:
    """Маркерное значение витрины по пути (без кэша приложения)."""
    con = duckdb.connect(str(path), read_only=True)
    try:
        row = con.execute("SELECT v FROM probe").fetchone()
        assert row is not None
        return int(row[0])
    finally:
        con.close()


# --- Проверка схемы входа и приём выгрузки ---------------------------------------------


def test_check_incoming_schema_rejects_missing_columns(tmp_path: Path) -> None:
    """Неполная схема отклоняется с перечислением недостающих колонок."""
    bad = tmp_path / "bad.parquet"
    make_parquet(bad, drop_columns=("indicator_value", "object_okato"))
    with pytest.raises(refresh.RefreshError, match="indicator_value"):
        refresh.check_incoming_schema(bad)


def test_check_incoming_schema_rejects_non_parquet(tmp_path: Path) -> None:
    """Файл, не являющийся parquet, отклоняется до каких-либо действий с витриной."""
    junk = tmp_path / "junk.parquet"
    junk.write_text("это не parquet", encoding="utf-8")
    with pytest.raises(refresh.RefreshError, match="не читается"):
        refresh.check_incoming_schema(junk)


def test_ingest_rewrites_registry_preserving_comments(tmp_path: Path) -> None:
    """Приём новой версии: файл скопирован, реестр перенацелен, комментарии целы."""
    repo = tmp_path
    registry = repo / "config" / "sources.yaml"
    write_registry(registry, "data/raw/data_v1.parquet")
    make_parquet(repo / "data" / "raw" / "data_v1.parquet")
    incoming = tmp_path / "загрузки" / "data_v2.parquet"
    make_parquet(incoming)

    accepted = refresh.ingest_incoming(incoming, registry, repo)

    assert accepted == repo / "data" / "raw" / "data_v2.parquet"
    assert accepted.exists()
    text = registry.read_text(encoding="utf-8")
    assert "path: data/raw/data_v2.parquet" in text
    assert "# Реестр источников" in text, "комментарии реестра должны сохраняться"
    assert "na_values: [-99999999, -77777777]" in text
    assert refresh.registered_source_path(registry) == Path("data/raw/data_v2.parquet")


def test_ingest_same_name_keeps_registry_text(tmp_path: Path) -> None:
    """Выгрузка с тем же именем перезаписывает сырьё, не трогая текст реестра."""
    repo = tmp_path
    registry = repo / "config" / "sources.yaml"
    write_registry(registry, "data/raw/data_v1.parquet")
    incoming = tmp_path / "data_v1.parquet"
    make_parquet(incoming)
    before = registry.read_text(encoding="utf-8")

    refresh.ingest_incoming(incoming, registry, repo)

    assert registry.read_text(encoding="utf-8") == before


# --- Валидация staging-витрины ---------------------------------------------------------


def test_validate_rejects_empty_required_table(tmp_path: Path) -> None:
    """Пустая ключевая таблица — отказ (битую сборку в бой не пускаем)."""
    staging = tmp_path / "staging.duckdb"
    make_store(staging)
    con = duckdb.connect(str(staging))
    con.execute("DELETE FROM dev_index")
    con.close()
    with pytest.raises(refresh.RefreshError, match="dev_index"):
        refresh.validate_staging(staging, current=None)


def test_validate_rejects_suspicious_region_count(tmp_path: Path) -> None:
    """Число регионов вне санитарного диапазона — признак чужой/битой выгрузки."""
    staging = tmp_path / "staging.duckdb"
    make_store(staging, regions=3)
    with pytest.raises(refresh.RefreshError, match="подозрительно"):
        refresh.validate_staging(staging, current=None)


def test_validate_rejects_freshness_regression(tmp_path: Path) -> None:
    """Подмена более старым срезом отклоняется: MAX(year) не должен откатываться."""
    current = tmp_path / "prod.duckdb"
    staging = tmp_path / "staging.duckdb"
    make_store(current, year=2024)
    make_store(staging, year=2023)
    with pytest.raises(refresh.RefreshError, match="откатилась"):
        refresh.validate_staging(staging, current=current)


def test_validate_accepts_fresh_store(tmp_path: Path) -> None:
    """Корректная свежая витрина проходит проверку и возвращает сводку."""
    current = tmp_path / "prod.duckdb"
    staging = tmp_path / "staging.duckdb"
    make_store(current, year=2024)
    make_store(staging, year=2025)
    summary = refresh.validate_staging(staging, current=current)
    assert summary == {"regions": 85, "max_year": 2025}


# --- Подмена и ротация бэкапов ---------------------------------------------------------


def test_swap_creates_backup_replaces_and_prunes(tmp_path: Path) -> None:
    """Подмена: бэкап текущей витрины, staging становится боевой, ротация хранит N."""
    target = tmp_path / "regionlens.duckdb"
    backups = tmp_path / "backups"
    make_store(target, probe=1)

    for version in (2, 3, 4):
        staging = tmp_path / "staging.duckdb"
        make_store(staging, probe=version)
        backup = refresh.swap_store(staging, target, backups, keep=2)
        assert backup is not None and backup.exists()
        assert not staging.exists(), "staging перемещается, а не копируется"
        assert read_probe(target) == version

    kept = sorted(backups.glob("regionlens_*.duckdb"))
    assert len(kept) == 2, "ротация должна хранить ровно keep последних бэкапов"
    # Свежайший бэкап — витрина, которую только что заменили (probe=3).
    assert read_probe(kept[-1]) == 3


def test_swap_without_existing_target(tmp_path: Path) -> None:
    """Первый запуск (боевой витрины ещё нет): подмена без бэкапа."""
    target = tmp_path / "regionlens.duckdb"
    staging = tmp_path / "staging.duckdb"
    make_store(staging, probe=7)
    backup = refresh.swap_store(staging, target, tmp_path / "backups", keep=3)
    assert backup is None
    assert read_probe(target) == 7


# --- Горячее переподключение приложения ------------------------------------------------


@pytest.mark.skipif(
    os.name == "nt",
    reason=(
        "Подмена файла под ОТКРЫТЫМ читателем — Linux-семантика (боевая платформа): "
        "Windows запрещает os.replace занятого файла на уровне ОС (WinError 5), "
        "поэтому сам проверяемый сценарий на этой платформе невозможен. "
        "Кроссплатформенный вариант с закрытием читателя — тест ниже."
    ),
)
def test_duck_reconnects_after_file_swap(tmp_path: Path, settings, monkeypatch) -> None:
    """После атомарной подмены файла q() видит новую витрину без reset_connection.

    Именно этот механизм позволяет воркерам gunicorn подхватывать обновление без
    рестарта. Интервал троттлинга статов обнуляется, чтобы тест был мгновенным.
    """
    store = tmp_path / "regionlens.duckdb"
    make_store(store, probe=1)
    settings.DUCKDB_PATH = str(store)
    monkeypatch.setattr(duck, "_STAT_INTERVAL", 0.0)
    duck.reset_connection()
    try:
        assert duck.q("SELECT v FROM probe")[0]["v"] == 1

        fresh = tmp_path / "fresh.duckdb"
        make_store(fresh, probe=2)
        os.replace(fresh, store)

        assert duck.q("SELECT v FROM probe")[0]["v"] == 2
    finally:
        duck.reset_connection()


def test_duck_reconnects_after_reset_and_swap(tmp_path: Path, settings, monkeypatch) -> None:
    """Кроссплатформенный сценарий: reset закрывает читателя, подмена, переподключение.

    На Windows это ЕДИНСТВЕННЫЙ возможный порядок (ОС не даёт заменить открытый
    файл); проверяется, что reset_connection освобождает файл детерминированно
    (явное закрытие, а не «когда-нибудь по GC») и что смена сигнатуры после подмены
    открывает уже новую витрину.
    """
    store = tmp_path / "regionlens.duckdb"
    make_store(store, probe=1)
    settings.DUCKDB_PATH = str(store)
    monkeypatch.setattr(duck, "_STAT_INTERVAL", 0.0)
    duck.reset_connection()
    try:
        assert duck.q("SELECT v FROM probe")[0]["v"] == 1

        duck.reset_connection()  # закрыть читателя — файл освобождён немедленно
        fresh = tmp_path / "fresh.duckdb"
        make_store(fresh, probe=2)
        os.replace(fresh, store)

        assert duck.q("SELECT v FROM probe")[0]["v"] == 2
    finally:
        duck.reset_connection()


# --- Сквозной прогон команды (сборка подменена мини-витриной) --------------------------


@pytest.fixture
def refresh_env(tmp_path: Path, settings):
    """Изолированное «дерево репозитория» для команды: витрина, реестр, каталог приёма."""
    settings.REPO_ROOT = tmp_path
    settings.DUCKDB_PATH = str(tmp_path / "data" / "regionlens.duckdb")
    settings.SOURCES_REGISTRY = str(tmp_path / "config" / "sources.yaml")
    settings.DATA_INCOMING_DIR = str(tmp_path / "data" / "incoming")
    write_registry(Path(settings.SOURCES_REGISTRY), "data/raw/data_v1.parquet")
    make_store(Path(settings.DUCKDB_PATH), year=2024, probe=1)
    duck.reset_connection()
    yield tmp_path
    duck.reset_connection()


def test_command_full_flow_from_incoming_dir(refresh_env: Path, monkeypatch) -> None:
    """Полный цикл: приём из каталога, «сборка», проверка, бэкап, подмена, архив файла."""
    incoming_dir = refresh_env / "data" / "incoming"
    incoming_dir.mkdir(parents=True)
    make_parquet(incoming_dir / "data_v2.parquet")

    def fake_build(staging: Path, sources_path: Path) -> None:
        # Реальная сборка конвейера здесь не нужна: проверяется процедура вокруг неё.
        make_store(staging, year=2025, probe=2)

    monkeypatch.setattr(refresh, "build_staging", fake_build)

    out = StringIO()
    call_command("refresh_data", stdout=out)

    target = refresh_env / "data" / "regionlens.duckdb"
    assert read_probe(target) == 2, "боевая витрина подменена собранной"
    assert list((refresh_env / "data" / "backups").glob("regionlens_*.duckdb"))
    assert not list(incoming_dir.glob("*.parquet")), "принятый файл убран из каталога приёма"
    assert list((incoming_dir / "processed").glob("*_data_v2.parquet"))
    registry_text = Path(refresh_env / "config" / "sources.yaml").read_text(encoding="utf-8")
    assert "path: data/raw/data_v2.parquet" in registry_text
    assert duck.q("SELECT MAX(year) AS y FROM fact_region")[0]["y"] == 2025


def test_command_rejects_regression_and_keeps_store(refresh_env: Path, monkeypatch) -> None:
    """Откат свежести: команда падает с CommandError, витрина и реестр не тронуты."""
    incoming_dir = refresh_env / "data" / "incoming"
    incoming_dir.mkdir(parents=True)
    make_parquet(incoming_dir / "data_v2.parquet")

    def stale_build(staging: Path, sources_path: Path) -> None:
        make_store(staging, year=2023, probe=9)  # старее текущей (2024)

    monkeypatch.setattr(refresh, "build_staging", stale_build)

    with pytest.raises(CommandError, match="не изменена"):
        call_command("refresh_data", stdout=StringIO())

    target = refresh_env / "data" / "regionlens.duckdb"
    assert read_probe(target) == 1, "боевая витрина осталась прежней"
    assert list(incoming_dir.glob("data_v2.parquet")), "файл не архивируется при отказе"


def test_command_requires_source_when_incoming_empty(refresh_env: Path) -> None:
    """Пустой каталог приёма без --source — понятная ошибка, а не тихий no-op."""
    with pytest.raises(CommandError, match="нет выгрузок"):
        call_command("refresh_data", stdout=StringIO())


def test_command_explicit_source(refresh_env: Path, monkeypatch, tmp_path: Path) -> None:
    """Явный --source: файл принимается по указанному пути и НЕ архивируется.

    Архивация — механика каталога приёма (гасит systemd path-юнит); файл, указанный
    пользователем явно, принадлежит пользователю и остаётся на месте.
    """
    incoming = tmp_path / "внешняя" / "data_v3.parquet"
    make_parquet(incoming)
    monkeypatch.setattr(
        refresh, "build_staging", lambda staging, sources: make_store(staging, year=2025, probe=3)
    )

    call_command("refresh_data", source=str(incoming), stdout=StringIO())

    assert read_probe(Path(refresh_env / "data" / "regionlens.duckdb")) == 3
    assert incoming.exists(), "явно указанный файл пользователя не перемещается"


def test_command_skip_ingest_rebuilds_from_current_raw(refresh_env: Path, monkeypatch) -> None:
    """--skip-ingest: пересборка без нового файла (реестр и сырьё не трогаются)."""
    registry = Path(refresh_env / "config" / "sources.yaml")
    before = registry.read_text(encoding="utf-8")
    monkeypatch.setattr(
        refresh, "build_staging", lambda staging, sources: make_store(staging, year=2024, probe=5)
    )

    call_command("refresh_data", skip_ingest=True, stdout=StringIO())

    assert read_probe(Path(refresh_env / "data" / "regionlens.duckdb")) == 5
    assert registry.read_text(encoding="utf-8") == before
