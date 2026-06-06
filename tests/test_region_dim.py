"""Тесты ETL S2: справочник регионов region_dim (правило грани 2 — ключ OKATO)."""

from __future__ import annotations

import polars as pl

from pipeline.etl import _variant_kind, build_region_dim


def test_variant_kind_handles_singular_and_plural() -> None:
    """Маркер «с/без АО» ловится и в единственном (Архангельская), и во множественном
    (Тюменская) числе; самостоятельный округ-субъект — это обычный регион."""
    assert _variant_kind("Архангельская область (без автономного округа)") == "without"
    assert _variant_kind("Архангельская область (с автономным округом)") == "with"
    assert _variant_kind("Тюменская область (без автономных округов)") == "without"
    assert _variant_kind("Тюменская область (с автономными округами)") == "with"
    assert _variant_kind("Ненецкий автономный округ") == "none"
    assert _variant_kind("Республика Татарстан") == "none"


def test_region_dim_key_variants_and_district() -> None:
    """geojson_key=okato; оба варианта «с/без АО» помечены; ФО из конфига; агрегат «с АО»
    исключён, «без АО» включён (include_with_autonomous_okrug=false)."""
    region = pl.DataFrame(
        {
            "object_okato": ["92000000", "11000000", "11200000", "71000000", "71200000"],
            "object_oktmo": ["92000000", "11000000", "11200000", "71000000", "71200000"],
            "object_name": [
                "Республика Татарстан",
                "Архангельская область (без автономного округа)",
                "Архангельская область (с автономным округом)",
                "Тюменская область (без автономных округов)",
                "Тюменская область (с автономными округами)",
            ],
        }
    )
    cfg = {
        "federal_districts": {"92000000": "Приволжский"},
        "aggregate_variants": {"include_with_autonomous_okrug": False},
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
    assert dim.height == 5
    assert (dim["geojson_key"] == dim["okato"]).all()
    # из 5 строк включены 3: Татарстан + два «без АО»; два агрегата «с АО» исключены
    assert dim.filter(pl.col("included_flag")).height == 3
    assert dim.filter(pl.col("is_aggregate_variant")).height == 4  # обе пары вариантов

    tat = dim.filter(pl.col("okato") == "92000000").row(0, named=True)
    assert tat["federal_district"] == "Приволжский"
    assert not tat["is_aggregate_variant"]
    assert tat["included_flag"]

    for ok in ("11000000", "71000000"):  # «без АО» — включены
        row = dim.filter(pl.col("okato") == ok).row(0, named=True)
        assert row["is_aggregate_variant"] and row["included_flag"]
    for ok in ("11200000", "71200000"):  # «с АО» (агрегат) — исключены
        row = dim.filter(pl.col("okato") == ok).row(0, named=True)
        assert row["is_aggregate_variant"] and not row["included_flag"]


def test_region_dim_empty_fd_map_gives_null_district() -> None:
    """Пустой маппинг ФО -> federal_district = null; обычный регион всегда включён."""
    region = pl.DataFrame(
        {
            "object_okato": ["92000000"],
            "object_oktmo": ["92000000"],
            "object_name": ["Республика Татарстан"],
        }
    )
    dim = build_region_dim(region, {"federal_districts": {}, "aggregate_variants": {}})
    assert dim.height == 1
    assert dim["federal_district"].null_count() == 1
    assert dim["included_flag"][0]
