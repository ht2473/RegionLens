"""Тесты ETL S2: справочник регионов region_dim (правило грани 2 — ключ OKATO)."""

from __future__ import annotations

import polars as pl

from pipeline.etl import build_region_dim


def test_region_dim_key_variants_and_district() -> None:
    """geojson_key=okato; варианты «с/без АО» помечены; ФО из конфига; лишний вариант исключён."""
    region = pl.DataFrame(
        {
            "object_okato": ["92000000000", "11000000000", "11000000001", "71000000000"],
            "object_oktmo": ["92000000", "11000000", "11000000", "71000000"],
            "object_name": [
                "Республика Татарстан",
                "Архангельская область без автономного округа",
                "Архангельская область с автономным округом",
                "Тюменская область с автономным округом",
            ],
        }
    )
    cfg = {
        "federal_districts": {"92000000000": "Приволжский"},
        "aggregate_variants": {"include_with_autonomous_okrug": True},
    }
    dim = build_region_dim(region, cfg)

    assert set(dim.columns) == {
        "okato",
        "oktmo",
        "region_name",
        "is_aggregate_variant",
        "federal_district",
        "included_flag",
        "geojson_key",
    }
    assert dim.height == 4
    assert (dim["geojson_key"] == dim["okato"]).all()

    tat = dim.filter(pl.col("okato") == "92000000000").row(0, named=True)
    assert tat["federal_district"] == "Приволжский"
    assert not tat["is_aggregate_variant"]
    assert tat["included_flag"]

    without = dim.filter(pl.col("okato") == "11000000000").row(0, named=True)
    assert without["is_aggregate_variant"]
    assert not without["included_flag"]  # include_with=True -> «без АО» исключён

    with_ao = dim.filter(pl.col("okato") == "11000000001").row(0, named=True)
    assert with_ao["included_flag"]  # «с АО» включён


def test_region_dim_empty_fd_map_gives_null_district() -> None:
    """Пустой маппинг ФО (текущее состояние regions.yaml) -> federal_district = null."""
    region = pl.DataFrame(
        {
            "object_okato": ["92000000000"],
            "object_oktmo": ["92000000"],
            "object_name": ["Республика Татарстан"],
        }
    )
    dim = build_region_dim(region, {"federal_districts": {}, "aggregate_variants": {}})
    assert dim.height == 1
    assert dim["federal_district"].null_count() == 1
    assert dim["included_flag"][0]  # обычный регион всегда включён
