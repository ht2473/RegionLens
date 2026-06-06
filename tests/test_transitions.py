"""Тесты переходов (Ф5 / S6, M1): ранг типов и переходы год-к-году."""

from __future__ import annotations

import polars as pl

from pipeline.transitions import build_transitions, cluster_rank


def _clusters() -> pl.DataFrame:
    """3 региона × 3 года. r1 всегда тип 2 (богатый), r2 всегда 0 (бедный),
    r3 переходит 0→1→2 (догоняющий)."""
    rows = [
        ("r1", 2010, 2),
        ("r1", 2011, 2),
        ("r1", 2012, 2),
        ("r2", 2010, 0),
        ("r2", 2011, 0),
        ("r2", 2012, 0),
        ("r3", 2010, 0),
        ("r3", 2011, 1),
        ("r3", 2012, 2),
    ]
    return pl.DataFrame(
        {
            "okato": [r[0] for r in rows],
            "year": [r[1] for r in rows],
            "cluster_id": [r[2] for r in rows],
        }
    )


def _dev_index() -> pl.DataFrame:
    """total_score: тип 2 — высокий, тип 1 — средний, тип 0 — низкий."""
    score = {0: 20.0, 1: 50.0, 2: 80.0}
    cl = _clusters()
    return cl.with_columns(
        pl.col("cluster_id").replace_strict(score).alias("total_score"),
        pl.lit("equal").alias("weighting_scheme"),
    ).select(["okato", "year", "weighting_scheme", "total_score"])


def test_cluster_rank_orders_by_score() -> None:
    """Ранг растёт с уровнем развития: тип 0 -> ранг 0, тип 2 -> ранг 2."""
    rank = cluster_rank(_dev_index(), _clusters())
    rmap = {int(r["cluster_id"]): int(r["cluster_rank"]) for r in rank.to_dicts()}
    assert rmap[0] == 0 and rmap[1] == 1 and rmap[2] == 2


def test_build_transitions_count_and_direction() -> None:
    """Переходов = (лет−1)×регионов; у догоняющего региона rank_delta>0."""
    clusters = _clusters()
    rank = cluster_rank(_dev_index(), clusters)
    trans = build_transitions(clusters, rank)
    assert trans.height == 3 * (3 - 1)  # 3 региона × 2 перехода
    # r3: 0->1 и 1->2 — оба «вверх» (rank_delta>0)
    r3 = trans.filter(pl.col("okato") == "r3").sort("year_from")
    assert r3["rank_delta"].to_list() == [1, 1]
    assert r3["cluster_from"].to_list() == [0, 1]
    assert r3["cluster_to"].to_list() == [1, 2]
    # r1 стабилен: rank_delta = 0
    r1 = trans.filter(pl.col("okato") == "r1")
    assert r1["rank_delta"].unique().to_list() == [0]
