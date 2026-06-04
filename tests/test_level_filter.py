"""Тесты ETL S2: разнос по object_level и загрузка адаптеров по конфигу."""

from __future__ import annotations

from pathlib import Path

import polars as pl

from pipeline.etl import build_source_adapters, read_sources, split_by_level
from pipeline.ingestion.base import CANONICAL


def _full_canonical_row() -> dict[str, object]:
    """Полная валидная строка канонической схемы (14 полей)."""
    return {
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
        "comment": "x",
        "source": "Регионы России 2020",
        "version_date": "2020-12-31",
    }


def test_split_keeps_only_region_in_region_slice() -> None:
    """В region попадают только строки уровня 'Регион'; ФО/Страна — в свои слои."""
    df = pl.DataFrame(
        {
            "object_level": ["Регион", "Федеральный округ", "Страна", "Регион"],
            "object_okato": ["92000000000", "36000000000", "00000000000", "01000000000"],
            "indicator_value": [1.0, 2.0, 3.0, 4.0],
        }
    )
    split = split_by_level(df)
    assert split.region.height == 2
    assert split.okrug.height == 1
    assert split.country.height == 1
    assert set(split.region["object_level"].unique().to_list()) == {"Регион"}


def test_unknown_level_not_lost_silently() -> None:
    """Строка с неизвестным уровнем не попадает ни в один слой."""
    df = pl.DataFrame(
        {
            "object_level": ["Регион", "Муниципалитет"],
            "object_okato": ["92000000000", "92401000000"],
            "indicator_value": [1.0, 2.0],
        }
    )
    split = split_by_level(df)
    assert split.region.height == 1
    assert split.okrug.height == 0
    assert split.country.height == 0


def test_build_adapters_from_config_and_read(tmp_path: Path) -> None:
    """build_source_adapters резолвит класс по dotted-пути и читает источник."""
    parquet = tmp_path / "src.parquet"
    pl.DataFrame([_full_canonical_row()]).write_parquet(parquet)
    cfg = [
        {
            "id": "test",
            "adapter": "pipeline.ingestion.rosstat_collection.RosstatCollectionAdapter",
            "path": str(parquet),
        }
    ]
    df = read_sources(build_source_adapters(cfg))
    assert df.columns == CANONICAL
    assert df.height == 1
