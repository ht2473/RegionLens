"""Тесты записи/чтения DuckDB и сборки fact_region."""

from __future__ import annotations

from pathlib import Path

import polars as pl

from pipeline.duck import list_tables, read_table, write_table
from pipeline.etl import build_fact_region


def test_write_read_roundtrip(tmp_path: Path) -> None:
    """Запись polars DataFrame в DuckDB и чтение обратно сохраняет данные."""
    db = str(tmp_path / "t.duckdb")
    df = pl.DataFrame(
        {"okato": ["92000000000"], "metric_id": [1], "year": [2015], "value": [3853.9]}
    )
    write_table(db, "fact_region", df)
    back = read_table(db, "fact_region")
    assert back.height == 1
    assert set(back.columns) == {"okato", "metric_id", "year", "value"}
    assert "fact_region" in list_tables(db)


def test_write_table_replaces(tmp_path: Path) -> None:
    """CREATE OR REPLACE: повторная запись заменяет таблицу, а не дополняет."""
    db = str(tmp_path / "t.duckdb")
    write_table(db, "t", pl.DataFrame({"a": [1, 2]}))
    write_table(db, "t", pl.DataFrame({"a": [9]}))
    assert read_table(db, "t").height == 1


def test_build_fact_region_columns() -> None:
    """fact_region содержит только okato/metric_id/year/value/source (okato из object_okato)."""
    region = pl.DataFrame(
        {
            "object_okato": ["92000000000"],
            "metric_id": [1],
            "year": [2015],
            "indicator_value": [3853.9],
            "source": ["Сборник 2021"],
            "object_name": ["Татарстан"],  # лишняя колонка не должна попасть в факт
        }
    )
    fact = build_fact_region(region)
    assert fact.columns == ["okato", "metric_id", "year", "value", "source"]
    assert fact["okato"][0] == "92000000000"
    assert fact["value"][0] == 3853.9
