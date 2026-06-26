"""Чувствительность ранга к выбору схемы весов (модуль «rank_robustness», лаборатория индекса).

Производная описательная мера поверх готового dev_index. Композитный индекс зависит от
произвольного выбора схемы взвешивания (равные / PCA / экспертные). Здесь мы делаем эту
зависимость видимой: для каждого года считаем ранг региона ОТДЕЛЬНО по каждой схеме (как в
выдаче рейтинга), а затем по региону за год берём «коридор» — от лучшей позиции среди схем до
худшей. Узкий коридор ⇒ вывод о месте региона устойчив; широкий ⇒ это во многом артефакт весов.

Это НЕ обучаемая модель, НЕ прогноз и НЕ вывод о причинах — только арифметика над уже
посчитанными баллами. Ранг проставляется как в рейтинге: `rank(method="ordinal",
descending=True)` внутри (схема, год). Грань результата — (okato, year).
"""

from dataclasses import dataclass

import polars as pl

from pipeline.contracts import RANK_ROBUSTNESS_SCHEMA
from pipeline.duck import read_table, write_table
from pipeline.logging_setup import log

DEFAULT_DUCKDB_PATH = "data/regionlens.duckdb"


@dataclass
class RankRobustnessResult:
    """Итог модуля: таблица rank_robustness (коридор ранга по схемам на регион-год)."""

    rank_robustness: pl.DataFrame


def compute_rank_robustness(dev_index: pl.DataFrame) -> pl.DataFrame:
    """Коридор ранга региона по схемам весов в каждом году (грань okato, year).

    Ранг проставляется внутри (weighting_scheme, year) по убыванию total_score. Затем по
    (okato, year) агрегируем ПО СХЕМАМ: rank_best (лучшая позиция = min ранг), rank_worst
    (худшая = max), rank_range = worst − best, плюс диапазон балла. Возвращает DataFrame по
    контракту RANK_ROBUSTNESS_SCHEMA.
    """
    ranked = dev_index.filter(pl.col("total_score").is_not_null()).with_columns(
        pl.col("total_score")
        .rank(method="ordinal", descending=True)
        .over(["weighting_scheme", "year"])
        .cast(pl.Int32)
        .alias("rank")
    )
    out = (
        ranked.group_by(["okato", "year"])
        .agg(
            pl.col("weighting_scheme").n_unique().alias("n_schemes"),
            pl.col("rank").min().alias("rank_best"),
            pl.col("rank").max().alias("rank_worst"),
            pl.col("rank").mean().alias("rank_mean"),
            pl.col("total_score").min().alias("score_min"),
            pl.col("total_score").max().alias("score_max"),
        )
        .with_columns((pl.col("rank_worst") - pl.col("rank_best")).alias("rank_range"))
    )
    return (
        out.select(list(RANK_ROBUSTNESS_SCHEMA))
        .with_columns(
            pl.col("year").cast(pl.Int32),
            pl.col("n_schemes").cast(pl.Int32),
            pl.col("rank_best").cast(pl.Int32),
            pl.col("rank_worst").cast(pl.Int32),
            pl.col("rank_range").cast(pl.Int32),
        )
        .sort(["year", "rank_best", "okato"])
    )


def run_rank_robustness(
    dev_index: pl.DataFrame,
    *,
    duckdb_path: str = DEFAULT_DUCKDB_PATH,
    write: bool = True,
) -> RankRobustnessResult:
    """Посчитать rank_robustness и (при write=True) записать контрактную таблицу в DuckDB."""
    rr = compute_rank_robustness(dev_index)
    log.info(
        "rank_robustness_built",
        stage="rank_robustness",
        rows=rr.height,
        regions=rr["okato"].n_unique(),
        max_rank_range=max(rr["rank_range"].to_list(), default=0),
    )
    if write:
        write_table(duckdb_path, "rank_robustness", rr)
    return RankRobustnessResult(rank_robustness=rr)


if __name__ == "__main__":
    dev = read_table(DEFAULT_DUCKDB_PATH, "dev_index")
    run_rank_robustness(dev)
