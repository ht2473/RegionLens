"""Тесты переходов: ранг типов, переходы год-к-году, типология траекторий."""

from __future__ import annotations

import polars as pl

from pipeline.transitions import (
    build_transitions,
    classify_trajectory,
    cluster_rank,
    run_transitions,
    trajectory_descriptors,
)


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
    return (
        _clusters()
        .with_columns(
            pl.col("cluster_id").replace_strict(score).alias("total_score"),
            pl.lit("equal").alias("weighting_scheme"),
        )
        .select(["okato", "year", "weighting_scheme", "total_score"])
    )


def test_cluster_rank_orders_by_score() -> None:
    """Ранг растёт с уровнем развития: тип 0 -> ранг 0, тип 2 -> ранг 2."""
    rmap = {
        int(r["cluster_id"]): int(r["cluster_rank"])
        for r in cluster_rank(_dev_index(), _clusters()).to_dicts()
    }
    assert rmap[0] == 0 and rmap[1] == 1 and rmap[2] == 2


def test_build_transitions_count_and_direction() -> None:
    """Переходов = (лет−1)×регионов; у догоняющего региона rank_delta>0."""
    clusters = _clusters()
    trans = build_transitions(clusters, cluster_rank(_dev_index(), clusters))
    assert trans.height == 3 * (3 - 1)
    r3 = trans.filter(pl.col("okato") == "r3").sort("year_from")
    assert r3["rank_delta"].to_list() == [1, 1]
    assert trans.filter(pl.col("okato") == "r1")["rank_delta"].unique().to_list() == [0]


def test_classify_trajectory_rules() -> None:
    """Правила типологии: стабильные по конечному рангу; рост/падение/волатильность."""
    assert classify_trajectory(2, 2, 0, 3, 2, 3) == "stable_high"
    assert classify_trajectory(0, 0, 0, 3, 2, 3) == "stable_low"
    assert classify_trajectory(1, 1, 0, 3, 2, 3) == "stable_mid"
    assert classify_trajectory(0, 2, 2, 3, 2, 3) == "leapfrogger"  # рост на 2, мало смен
    assert classify_trajectory(0, 2, 4, 3, 2, 3) == "converger"  # рост на 2, много смен
    assert classify_trajectory(2, 0, 2, 3, 2, 3) == "diverger"  # падение на 2
    assert classify_trajectory(1, 1, 4, 3, 2, 3) == "volatile"  # без нетто-сдвига, частые смены
    assert classify_trajectory(0, 1, 1, 3, 2, 3) == "drifting"  # малый сдвиг, редкие смены


def test_trajectory_descriptors_and_run() -> None:
    """Дескрипторы: r3 — 2 смены, ранг 0→2; run_transitions проставляет trajectory_type всем."""
    clusters = _clusters()
    rank = cluster_rank(_dev_index(), clusters)
    desc = trajectory_descriptors(clusters, rank)
    r3 = desc.filter(pl.col("okato") == "r3").row(0, named=True)
    assert r3["n_changes"] == 2 and r3["initial_rank"] == 0 and r3["final_rank"] == 2

    out = run_transitions(clusters, _dev_index(), write=False).transitions
    assert set(out.columns) == {
        "okato",
        "year_from",
        "year_to",
        "cluster_from",
        "cluster_to",
        "trajectory_type",
    }
    assert out["trajectory_type"].null_count() == 0
    # r1 стабилен на верхнем ранге, r2 — на нижнем, r3 — догоняющий
    types = {r["okato"]: r["trajectory_type"] for r in out.unique("okato").to_dicts()}
    assert types["r1"] == "stable_high" and types["r2"] == "stable_low"
    assert types["r3"] in {"leapfrogger", "converger"}
