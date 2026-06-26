"""Тесты каталога метрик (pipeline.metric_catalog).

Детерминированная синтетика: правило тиринга (core / extended / sparse), фактический охват по
сырью (годы/регионы по непустым значениям, NULL исключаются) и соответствие контракту.
"""

import polars as pl

from pipeline.contracts import METRIC_CATALOG_SCHEMA
from pipeline.metric_catalog import (
    TIER_CORE,
    TIER_EXTENDED,
    TIER_SPARSE,
    compute_metric_catalog,
    run_metric_catalog,
)

# metric_dim: (metric_id, domain, coverage, higher_is_better|None)
MDRow = tuple[int, str, float, bool | None]
# fact_region: (okato, metric_id, year, value|None)
FRRow = tuple[str, int, int, float | None]


def _metric_dim(rows: list[MDRow]) -> pl.DataFrame:
    return pl.DataFrame(
        [
            (m, f"Y{m:06d}", f"Метрика {m}", dom, "absolute", "ед.", cov, hib)
            for (m, dom, cov, hib) in rows
        ],
        schema=[
            "metric_id",
            "indicator_code",
            "metric_name",
            "domain",
            "value_type",
            "unit",
            "coverage",
            "higher_is_better",
        ],
        orient="row",
    ).with_columns(pl.col("metric_id").cast(pl.Int32))


def _fact_region(rows: list[FRRow]) -> pl.DataFrame:
    return pl.DataFrame(
        [(o, m, y, v, "s") for (o, m, y, v) in rows],
        schema=["okato", "metric_id", "year", "value", "source"],
        orient="row",
    ).with_columns(pl.col("metric_id").cast(pl.Int32), pl.col("year").cast(pl.Int32))


def _by_id(md: pl.DataFrame, fr: pl.DataFrame) -> dict[int, dict]:
    rows = compute_metric_catalog(md, fr, extended_min_coverage=0.70).to_dicts()
    return {r["metric_id"]: r for r in rows}


def test_tiers_assigned_by_rule() -> None:
    """Правило тиров: core / extended (покрытие ≥ порога, домен ≠ excluded) / sparse."""
    md = _metric_dim(
        [
            (1, "economy", 0.90, True),  # core
            (2, "economy", 0.80, None),  # extended (≥0.7, домен ок)
            (3, "economy", 0.30, None),  # sparse (низкое покрытие)
            (4, "excluded", 0.95, None),  # sparse (домен excluded)
        ]
    )
    fr = _fact_region([("01", m, 2020, 1.0) for m in (1, 2, 3, 4)])
    by = _by_id(md, fr)

    assert by[1]["tier"] == TIER_CORE and by[1]["is_core"] is True
    assert by[2]["tier"] == TIER_EXTENDED and by[2]["is_core"] is False
    assert by[3]["tier"] == TIER_SPARSE
    assert by[4]["tier"] == TIER_SPARSE


def test_span_counts_from_nonnull_facts() -> None:
    """Охват (year_min/max, n_years, n_regions) — по непустым значениям; NULL не учитывается."""
    md = _metric_dim([(1, "economy", 0.9, None)])
    fr = _fact_region(
        [
            ("01", 1, 2018, 5.0),
            ("02", 1, 2020, 7.0),
            ("01", 1, 2021, None),  # NULL — не считается
            ("03", 1, 2019, 9.0),
        ]
    )
    row = compute_metric_catalog(md, fr, extended_min_coverage=0.70).to_dicts()[0]

    assert row["year_min"] == 2018 and row["year_max"] == 2020  # 2021 был NULL
    assert row["n_years"] == 3  # 2018, 2019, 2020
    assert row["n_regions"] == 3  # 01, 02, 03


def test_metric_without_facts_has_zero_span() -> None:
    """Метрика без непустых фактов: n_years/n_regions = 0, годы пусты (но строка присутствует)."""
    md = _metric_dim([(1, "economy", 0.9, None), (2, "economy", 0.9, None)])
    fr = _fact_region([("01", 1, 2020, 1.0)])  # для метрики 2 фактов нет
    by = _by_id(md, fr)

    assert by[2]["n_years"] == 0 and by[2]["n_regions"] == 0
    assert by[2]["year_min"] is None and by[2]["year_max"] is None


def test_contract_columns_and_types() -> None:
    """Результат соответствует контракту METRIC_CATALOG_SCHEMA по составу и типам колонок."""
    md = _metric_dim([(1, "economy", 0.9, True)])
    fr = _fact_region([("01", 1, 2020, 1.0)])
    cat = compute_metric_catalog(md, fr, extended_min_coverage=0.70)

    assert cat.columns == list(METRIC_CATALOG_SCHEMA)
    assert dict(zip(cat.columns, cat.dtypes, strict=True)) == METRIC_CATALOG_SCHEMA


def test_run_returns_table() -> None:
    """run_metric_catalog(write=False) возвращает таблицу со всеми метриками."""
    md = _metric_dim([(1, "economy", 0.9, True), (2, "economy", 0.8, None)])
    fr = _fact_region([("01", 1, 2020, 1.0), ("01", 2, 2020, 2.0)])
    result = run_metric_catalog(md, fr, write=False, extended_min_coverage=0.70)

    assert result.metric_catalog.height == 2
    assert set(result.metric_catalog["tier"].to_list()) == {TIER_CORE, TIER_EXTENDED}
