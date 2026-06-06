"""Переходы между типами и траектории регионов (Ф5 / S6).

Блок M1: ранг типов по уровню развития (dev_index) + переходы год-к-году.
Блок M2: дескрипторы траектории региона (нач./кон. ранг, число смен), типология
траекторий прозрачными правилами и запись таблицы transitions в DuckDB.
Блок M3 (отдельно): SHAP-объяснение направления перехода.

Пороги типологии — из config/analytics.yaml (trajectory); никакого хардкода.
"""

from dataclasses import dataclass

import polars as pl

from pipeline.config import load_config
from pipeline.duck import write_table
from pipeline.logging_setup import log

DEFAULT_DUCKDB_PATH = "data/regionlens.duckdb"


@dataclass
class TransitionsResult:
    """Итог Ф5: таблица переходов с типом траектории."""

    transitions: pl.DataFrame


def cluster_rank(
    dev_index: pl.DataFrame, clusters: pl.DataFrame, *, scheme: str = "equal"
) -> pl.DataFrame:
    """Ранг типа по среднему total_score (схема equal): 0 — самый низкий уровень развития.

    cluster_id стабилен во времени (Ф3), поэтому ранг считается один на тип по всему окну.
    Нужен, чтобы определять направление перехода (вверх/вниз).
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
    Ранги уровней (rank_from/rank_to) и их разность (rank_delta>0 — вверх по развитию).
    Число переходов = (лет−1)×регионов.
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


def classify_trajectory(
    initial_rank: int, final_rank: int, n_changes: int, k: int, leap_gap: int, volatile_changes: int
) -> str:
    """Тип траектории региона по дескрипторам (прозрачные правила).

    Без смен типа → stable_high/mid/low (по конечному рангу). Иначе по нетто-сдвигу ранга:
    рост ≥ leap_gap — leapfrogger (если смен мало) или converger; падение ≤ −leap_gap —
    diverger; в остальном volatile (частые смены) или drifting (редкие).
    """
    net = final_rank - initial_rank
    if n_changes == 0:
        if final_rank >= k - 1:
            return "stable_high"
        if final_rank == 0:
            return "stable_low"
        return "stable_mid"
    if net >= leap_gap:
        return "leapfrogger" if n_changes <= 2 else "converger"
    if net <= -leap_gap:
        return "diverger"
    return "volatile" if n_changes >= volatile_changes else "drifting"


def trajectory_descriptors(clusters: pl.DataFrame, rank: pl.DataFrame) -> pl.DataFrame:
    """Дескрипторы траектории на регион: начальный/конечный ранг и число смен типа.

    initial_rank/final_rank — ранг типа региона в первый/последний год окна; n_changes —
    сколько раз cluster_id менялся год-к-году. Возвращает okato + три дескриптора.
    """
    ranked = (
        clusters.select(["okato", "year", "cluster_id"])
        .join(rank.select(["cluster_id", "cluster_rank"]), on="cluster_id", how="left")
        .sort(["okato", "year"])
    )
    # число смен типа год-к-году по региону
    changes = (
        ranked.with_columns(
            (pl.col("cluster_id") != pl.col("cluster_id").shift(1).over("okato")).alias("_chg")
        )
        .group_by("okato")
        .agg((pl.col("_chg").fill_null(False)).sum().alias("n_changes"))
    )
    # начальный и конечный ранг (первый/последний год окна)
    first = ranked.group_by("okato").agg(
        pl.col("cluster_rank").sort_by("year").first().alias("initial_rank")
    )
    last = ranked.group_by("okato").agg(
        pl.col("cluster_rank").sort_by("year").last().alias("final_rank")
    )
    return changes.join(first, on="okato").join(last, on="okato")


def assign_trajectory_types(descriptors: pl.DataFrame, k: int) -> pl.DataFrame:
    """Назначить trajectory_type каждому региону по дескрипторам (пороги из конфига)."""
    traj = load_config("analytics").get("trajectory") or {}
    leap_gap = int(traj.get("leap_gap", 2))
    volatile_changes = int(traj.get("volatile_changes", 3))
    rows = [
        {
            "okato": d["okato"],
            "trajectory_type": classify_trajectory(
                int(d["initial_rank"]),
                int(d["final_rank"]),
                int(d["n_changes"]),
                k,
                leap_gap,
                volatile_changes,
            ),
        }
        for d in descriptors.to_dicts()
    ]
    return pl.DataFrame(rows)


def run_transitions(
    clusters: pl.DataFrame,
    dev_index: pl.DataFrame,
    *,
    duckdb_path: str = DEFAULT_DUCKDB_PATH,
    write: bool = True,
) -> TransitionsResult:
    """Ф5 целиком: ранг типов → переходы год-к-году → типология траекторий → запись.

    Итоговая таблица transitions (контракт): okato, year_from, year_to, cluster_from,
    cluster_to, trajectory_type. trajectory_type один на регион (тип всего пути), повторяется
    в его строках-переходах.
    """
    rank = cluster_rank(dev_index, clusters)
    k = rank.height
    trans = build_transitions(clusters, rank)
    descriptors = trajectory_descriptors(clusters, rank)
    traj = assign_trajectory_types(descriptors, k)

    out = (
        trans.join(traj, on="okato", how="left")
        .select(["okato", "year_from", "year_to", "cluster_from", "cluster_to", "trajectory_type"])
        .sort(["okato", "year_from"])
    )
    dist = traj.group_by("trajectory_type").len().sort("trajectory_type")
    log.info(
        "trajectory_types",
        stage="transitions",
        distribution={d["trajectory_type"]: d["len"] for d in dist.to_dicts()},
    )
    if write:
        write_table(duckdb_path, "transitions", out)
        log.info("transitions_written", stage="transitions", path=duckdb_path, rows=out.height)
    return TransitionsResult(transitions=out)


if __name__ == "__main__":
    from pipeline.duck import read_table

    cl = read_table(DEFAULT_DUCKDB_PATH, "clusters")
    di = read_table(DEFAULT_DUCKDB_PATH, "dev_index")
    run_transitions(cl, di)
