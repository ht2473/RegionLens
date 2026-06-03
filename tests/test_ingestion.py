"""Тесты слоя приёма данных (Ф1, S1): схема, типы, обработка ошибок."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from pipeline.ingestion.base import CANONICAL, MissingColumnsError, coerce_to_canonical
from pipeline.ingestion.rosstat_collection import RosstatCollectionAdapter


def _row(**over: object) -> dict[str, object]:
    """Одна валидная строка канонической схемы (поля можно переопределить)."""
    base: dict[str, object] = {
        "section": "Население",
        "indicator_code": "0001",
        "indicator_name": "Численность населения",
        "subsection": "Все население",
        "object_name": "Республика Татарстан",
        "object_level": "Регион",
        "object_oktmo": "92000000",
        "object_okato": "92000000000",
        "year": 2015,
        "indicator_value": 3853.9,
        "indicator_unit": "тысяча человек",
        "comment": "перепись",
        "source": "Регионы России 2020",
        "version_date": "2020-12-31",
    }
    base.update(over)
    return base


def _write(path: Path, rows: list[dict[str, object]]) -> Path:
    pl.DataFrame(rows).write_parquet(path)
    return path


def test_adapter_reads_canonical_schema(tmp_path: Path) -> None:
    """Адаптер читает parquet и возвращает ровно колонки CANONICAL."""
    p = _write(tmp_path / "src.parquet", [_row(), _row(year=2016, comment=None)])
    df = RosstatCollectionAdapter(p).read()
    assert df.columns == CANONICAL
    assert df.height == 2


def test_types_are_coerced(tmp_path: Path) -> None:
    """year -> Int64, indicator_value -> Float64; коды остаются строками с нулями."""
    row = _row(year="2015", indicator_value="100.5", object_okato="01000000000", comment="x")
    df = coerce_to_canonical(pl.read_parquet(_write(tmp_path / "s.parquet", [row])), source_id="t")
    assert df.schema["year"] == pl.Int64
    assert df.schema["indicator_value"] == pl.Float64
    assert df.schema["object_okato"] == pl.Utf8
    assert df["object_okato"][0] == "01000000000"  # ведущий ноль сохранён
    assert df["year"][0] == 2015


def test_missing_columns_raise() -> None:
    """Отсутствие колонок канонической схемы -> MissingColumnsError."""
    bad = pl.DataFrame({"year": [2010], "indicator_value": [1.0]})
    with pytest.raises(MissingColumnsError):
        coerce_to_canonical(bad, source_id="t")


def test_missing_file_raises(tmp_path: Path) -> None:
    """Несуществующий путь -> FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        RosstatCollectionAdapter(tmp_path / "nope.parquet").read()
