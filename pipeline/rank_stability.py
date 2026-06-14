"""Стабильность рейтинга регионов (модуль «rank_stability», Ф14).

Производная описательная мера поверх готового dev_index: для каждой схемы весов считаем
ранг региона по total_score внутри года (1 — выше всех, как на экране рейтинга), затем по
региону за окно — насколько ранг устойчив или скачет. Это НЕ обучаемая модель, НЕ прогноз
и НЕ вывод о причинах — только арифметика над уже посчитанными баллами.

Ранг считается так же, как в выдаче рейтинга (`ORDER BY total_score DESC` → позиция):
`rank(method="ordinal", descending=True)` внутри (схема, год). Статистики устойчивости:
rank_mean/std, rank_min/max/range и mean_abs_change — средний модуль годового изменения
ранга (мера «дёрганности» траектории). Регионы менее чем с min_years годами отбрасываются.

Параметр min_years — из config/analytics.yaml (rank_stability.min_years); без хардкода.
"""

from dataclasses import dataclass

import polars as pl

from pipeline.config import load_config
from pipeline.contracts import RANK_STABILITY_SCHEMA
from pipeline.duck import read_table, write_table
from pipeline.logging_setup import log

DEFAULT_DUCKDB_PATH = "data/regionlens.duckdb"


@dataclass
class RankStabilityResult:
    """Итог модуля: таблица rank_stability (волатильность ранга на регион-схему)."""

    rank_stability: pl.DataFrame


def compute_rank_stability(dev_index: pl.DataFrame, *, min_years: int) -> pl.DataFrame:
    """Статистики устойчивости ранга региона по индексу за годы, по каждой схеме весов.

    Возвращает DataFrame по контракту RANK_STABILITY_SCHEMA. Ранг проставляется внутри
    (weighting_scheme, year) по убыванию total_score; регионы менее чем с min_years
    наблюдениями отбрасываются (по одной-двум точкам волатильность непоказательна).
    """
    ranked = (
        dev_index.filter(pl.col("total_score").is_not_null())
        .with_columns(
            pl.col("total_score")
            .rank(method="ordinal", descending=True)
            .over(["weighting_scheme", "year"])
            .cast(pl.Int32)
            .alias("rank")
        )
        .sort(["weighting_scheme", "okato", "year"])
        .with_columns(
            pl.col("rank").diff().over(["weighting_scheme", "okato"]).abs().alias("_abs_change")
        )
    )
    out = (
        ranked.group_by(["okato", "weighting_scheme"])
        .agg(
            pl.col("year").len().alias("n_years"),
            pl.col("rank").mean().alias("rank_mean"),
            pl.col("rank").std().alias("rank_std"),
            pl.col("rank").min().alias("rank_min"),
            pl.col("rank").max().alias("rank_max"),
            pl.col("_abs_change").mean().alias("mean_abs_change"),
        )
        .filter(pl.col("n_years") >= min_years)
        .with_columns((pl.col("rank_max") - pl.col("rank_min")).alias("rank_range"))
    )
    return (
        out.select(list(RANK_STABILITY_SCHEMA))
        .with_columns(
            pl.col("n_years").cast(pl.Int32),
            pl.col("rank_min").cast(pl.Int32),
            pl.col("rank_max").cast(pl.Int32),
            pl.col("rank_range").cast(pl.Int32),
        )
        .sort(["weighting_scheme", "rank_std", "okato"])
    )


def run_rank_stability(
    dev_index: pl.DataFrame,
    *,
    duckdb_path: str = DEFAULT_DUCKDB_PATH,
    write: bool = True,
) -> RankStabilityResult:
    """Посчитать rank_stability и (при write=True) записать контрактную таблицу в DuckDB."""
    cfg = load_config("analytics").get("rank_stability") or {}
    min_years = int(cfg.get("min_years", 3))
    rs = compute_rank_stability(dev_index, min_years=min_years)
    log.info(
        "rank_stability_built",
        stage="rank_stability",
        rows=rs.height,
        regions=rs["okato"].n_unique(),
        schemes=rs["weighting_scheme"].n_unique(),
    )
    if write:
        write_table(duckdb_path, "rank_stability", rs)
    return RankStabilityResult(rank_stability=rs)


if __name__ == "__main__":
    dev = read_table(DEFAULT_DUCKDB_PATH, "dev_index")
    run_rank_stability(dev)
