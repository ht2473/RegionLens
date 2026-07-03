"""Каталог метрик: тиринг и профиль всего справочника метрик (поток «Данные»).

Производная сводка поверх готовых таблиц (ничего не моделирует и не пересчитывает заново):
по каждой метрике каталога определяем «тир» пригодности и фактический охват по сырью. Нужна как
основа explore-режима (что вообще доступно для анализа) и как доказательная база для расширения
ядра индекса/типологии.

Тиры:
- **core** — метрика входит в курируемое ядро (higher_is_better задан): питает индекс/типологию.
- **extended** — вне ядра, но хорошо покрыта (coverage ≥ порога) и домен не excluded: пригодна
  для explore-режима и кандидат на расширение ядра.
- **sparse** — слишком разрежена либо домен excluded: в аналитику по умолчанию не идёт.

Грань — metric_id. coverage берём из metric_dim (оконное покрытие). year_min/max/n_years/
n_regions считаем по fact_region на ПОЛНОМ окне сырья (2001–2025) — это наблюдаемая «свежесть/охват»
метрики, шире окна анализа. Порог extended — из config/analytics.yaml (без хардкода).
"""

from dataclasses import dataclass

import polars as pl

from pipeline.config import load_config
from pipeline.contracts import METRIC_CATALOG_SCHEMA
from pipeline.duck import read_table, write_table
from pipeline.logging_setup import log

DEFAULT_DUCKDB_PATH = "data/regionlens.duckdb"

TIER_CORE = "core"
TIER_EXTENDED = "extended"
TIER_SPARSE = "sparse"


@dataclass
class MetricCatalogResult:
    """Итог модуля: таблица metric_catalog (тиринг и профиль всех метрик)."""

    metric_catalog: pl.DataFrame


def _extended_min_coverage() -> float:
    """Порог покрытия для тира extended из config/analytics.yaml."""
    return float(load_config("analytics")["metric_catalog"]["extended_min_coverage"])


def compute_metric_catalog(
    metric_dim: pl.DataFrame, fact_region: pl.DataFrame, *, extended_min_coverage: float
) -> pl.DataFrame:
    """Тиринг и профиль каждой метрики каталога (грань metric_id).

    is_core ← higher_is_better задан в metric_dim. Охват (year_min/max, n_years, n_regions) ←
    непустые значения fact_region на всём окне сырья. tier по правилу: core → extended (покрытие ≥
    порога и домен не excluded) → sparse. Возвращает DataFrame по контракту METRIC_CATALOG_SCHEMA.
    """
    # Фактический охват по сырью: только непустые значения (заглушки уже занулены в ETL).
    present = fact_region.filter(pl.col("value").is_not_null())
    span = present.group_by("metric_id").agg(
        pl.col("year").min().alias("year_min"),
        pl.col("year").max().alias("year_max"),
        pl.col("year").n_unique().alias("n_years"),
        pl.col("okato").n_unique().alias("n_regions"),
    )

    cat = (
        metric_dim.select(
            "metric_id",
            "indicator_code",
            "metric_name",
            "domain",
            "value_type",
            "unit",
            "coverage",
            pl.col("higher_is_better").is_not_null().alias("is_core"),
        )
        .join(span, on="metric_id", how="left")
        .with_columns(
            pl.col("n_years").fill_null(0),
            pl.col("n_regions").fill_null(0),
        )
        .with_columns(
            pl.when(pl.col("is_core"))
            .then(pl.lit(TIER_CORE))
            .when((pl.col("coverage") >= extended_min_coverage) & (pl.col("domain") != "excluded"))
            .then(pl.lit(TIER_EXTENDED))
            .otherwise(pl.lit(TIER_SPARSE))
            .alias("tier")
        )
        .with_columns(
            pl.col("metric_id").cast(pl.Int32),
            pl.col("year_min").cast(pl.Int32),
            pl.col("year_max").cast(pl.Int32),
            pl.col("n_years").cast(pl.Int32),
            pl.col("n_regions").cast(pl.Int32),
        )
    )
    return cat.select(list(METRIC_CATALOG_SCHEMA)).sort("metric_id")


def run_metric_catalog(
    metric_dim: pl.DataFrame,
    fact_region: pl.DataFrame,
    *,
    duckdb_path: str = DEFAULT_DUCKDB_PATH,
    write: bool = True,
    extended_min_coverage: float | None = None,
) -> MetricCatalogResult:
    """Построить metric_catalog и (при write=True) записать контрактную таблицу в DuckDB."""
    threshold = _extended_min_coverage() if extended_min_coverage is None else extended_min_coverage
    cat = compute_metric_catalog(metric_dim, fact_region, extended_min_coverage=threshold)
    by_tier = dict(cat.group_by("tier").len().iter_rows())
    log.info(
        "metric_catalog_built",
        stage="metric_catalog",
        metrics=cat.height,
        core=by_tier.get(TIER_CORE, 0),
        extended=by_tier.get(TIER_EXTENDED, 0),
        sparse=by_tier.get(TIER_SPARSE, 0),
        extended_min_coverage=threshold,
    )
    if write:
        write_table(duckdb_path, "metric_catalog", cat)
    return MetricCatalogResult(metric_catalog=cat)


if __name__ == "__main__":
    md = read_table(DEFAULT_DUCKDB_PATH, "metric_dim")
    fr = read_table(DEFAULT_DUCKDB_PATH, "fact_region")
    run_metric_catalog(md, fr)
