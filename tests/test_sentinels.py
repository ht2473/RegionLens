"""Тесты зануления кодов «нет данных» (Ф2·М0): функция и проброс через адаптер."""

from __future__ import annotations

from pathlib import Path

import polars as pl

from pipeline.etl import build_source_adapters
from pipeline.ingestion.base import null_na_values
from pipeline.ingestion.rosstat_collection import RosstatCollectionAdapter
from tests.test_ingestion import _row, _write


def test_null_na_values_replaces_codes() -> None:
    """Заглушки превращаются в null, нормальные значения не трогаются."""
    df = pl.DataFrame({"indicator_value": [100.0, -99999999.0, 5.0, -77777777.0]})
    out = null_na_values(df, [-99999999, -77777777])
    assert out["indicator_value"].to_list() == [100.0, None, 5.0, None]


def test_null_na_values_noop_when_empty() -> None:
    """Пустой список кодов — DataFrame возвращается как есть (ничего не зануляем)."""
    df = pl.DataFrame({"indicator_value": [-99999999.0, 1.0]})
    assert null_na_values(df, None)["indicator_value"].to_list() == [-99999999.0, 1.0]
    assert null_na_values(df, [])["indicator_value"].to_list() == [-99999999.0, 1.0]


def test_adapter_nulls_sentinels_on_read(tmp_path: Path) -> None:
    """Адаптер с na_values зануляет заглушки прямо при чтении parquet."""
    rows = [_row(indicator_value=3853.9), _row(year=2016, indicator_value=-99999999.0)]
    p = _write(tmp_path / "src.parquet", rows)
    df = RosstatCollectionAdapter(p, na_values=[-99999999, -77777777]).read()
    vals = df.sort("year")["indicator_value"].to_list()
    assert vals == [3853.9, None]


def test_build_source_adapters_passes_na_values() -> None:
    """na_values из реестра источников доходит до адаптера (а без него — пустой)."""
    cfg = [
        {
            "adapter": "pipeline.ingestion.rosstat_collection.RosstatCollectionAdapter",
            "path": "data/raw/x.parquet",
            "na_values": [-99999999, -77777777],
        }
    ]
    adapter = build_source_adapters(cfg)[0]
    assert isinstance(adapter, RosstatCollectionAdapter)
    assert adapter.na_values == [-99999999, -77777777]

    cfg_no_na = [{"adapter": cfg[0]["adapter"], "path": "data/raw/x.parquet"}]
    assert build_source_adapters(cfg_no_na)[0].na_values == []
