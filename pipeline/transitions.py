"""Переходы между типами и траектории регионов (Ф5 / S6), блок M1: ранг типов и
переходы год-к-году.

Блок M1: ранжируем стабильные типы по уровню развития (средний total_score из dev_index,
схема equal) и строим переходы cluster_from→cluster_to по соседним годам на стабильных
cluster_id. Дескрипторы траектории, типология (stable_high/converger/diverger/…) и
SHAP-объяснение направления перехода — в блоке M2.
"""

import polars as pl

from pipeline.logging_setup import log

DEFAULT_DUCKDB_PATH = "data/regionlens.duckdb"


def cluster_rank(
    dev_index: pl.DataFrame, clusters: pl.DataFrame, *, scheme: str = "equal"
) -> pl.DataFrame:
    """Ранг типа по среднему total_score (схема equal): 0 — самый низкий уровень развития.

    cluster_id стабилен во времени (Ф3), поэтому ранг считается один на тип по всему окну.
    Нужен, чтобы определять направление перехода (вверх/вниз) в блоке M2.
    Возвращает cluster_id, cluster_rank (0..k−1), mean_score.
    """
    idx = dev_index.filter(pl.col("weighting_scheme") == scheme).select(
        ["okato", "year", "total_score"]
    )
    joined = clusters.select(["okato", "year", "cluster_id"]).join(
        idx, on=["okato", "year"], how="inner"
    )
    return (
        joined.group_by("cluster_id")
        .agg(pl.col("total_score").mean().alias("mean_score"))
        .sort("mean_score")
        .with_row_index("cluster_rank")
        .with_columns(pl.col("cluster_rank").cast(pl.Int32))
        .select(["cluster_id", "cluster_rank", "mean_score"])
    )


def build_transitions(clusters: pl.DataFrame, rank: pl.DataFrame) -> pl.DataFrame:
    """Переходы год-к-году на стабильных cluster_id, с рангами уровней from/to.

    Для каждого региона по соседним годам: (year_from, year_to, cluster_from, cluster_to).
    Ранги уровней (rank_from/rank_to) и их разность (rank_delta>0 — вверх по развитию)
    нужны блоку M2 для типологии траекторий. Число переходов = (лет−1)×регионов.
    """
    ordered = clusters.select(["okato", "year", "cluster_id"]).sort(["okato", "year"])
    trans = (
        ordered.with_columns(
            pl.col("cluster_id").shift(1).over("okato").alias("cluster_from"),
            pl.col("year").shift(1).over("okato").alias("year_from"),
        )
        .drop_nulls("cluster_from")
        .rename({"cluster_id": "cluster_to", "year": "year_to"})
        .select(["okato", "year_from", "year_to", "cluster_from", "cluster_to"])
    )
    rmap = rank.select(["cluster_id", "cluster_rank"])
    trans = (
        trans.join(
            rmap.rename({"cluster_id": "cluster_from", "cluster_rank": "rank_from"}),
            on="cluster_from",
            how="left",
        )
        .join(
            rmap.rename({"cluster_id": "cluster_to", "cluster_rank": "rank_to"}),
            on="cluster_to",
            how="left",
        )
        .with_columns((pl.col("rank_to") - pl.col("rank_from")).alias("rank_delta"))
        .sort(["okato", "year_from"])
    )
    log.info(
        "transitions_built",
        stage="transitions",
        rows=trans.height,
        regions=trans["okato"].n_unique(),
    )
    return trans
