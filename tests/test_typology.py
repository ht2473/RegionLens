"""Тесты типологии (Ф3 / S4, M1): венгерское согласование, выбор k, сборка clusters."""

from __future__ import annotations

import numpy as np
import polars as pl

from pipeline.typology import (
    align_labels,
    build_clusters,
    choose_k,
    compute_cluster_shap,
    run_typology,
    year_matrix,
)


def test_align_labels_remaps_permuted() -> None:
    """Перестановка номеров кластеров между годами выравнивается к предыдущему году."""
    okato = ["a", "b", "c", "d"]
    prev = np.array([0, 0, 1, 1])
    cur = np.array([1, 1, 0, 0])  # те же группы, но номера переставлены
    aligned = align_labels(prev, okato, cur, okato, k=2)
    assert aligned.tolist() == [0, 0, 1, 1]


def _synthetic_features() -> pl.DataFrame:
    """Два года, 6 регионов, 2 метрики: три явных кластера, стабильных во времени."""
    rng = np.random.default_rng(0)
    centers = {"lo": (-3.0, -3.0), "mid": (0.0, 0.0), "hi": (3.0, 3.0)}
    groups = {"lo": ["r1", "r2"], "mid": ["r3", "r4"], "hi": ["r5", "r6"]}
    rows = []
    for year in (2010, 2011):
        for g, oks in groups.items():
            cx, cy = centers[g]
            for ok in oks:
                noise = rng.normal(0, 0.1, 2)
                rows.append({"okato": ok, "year": year, "metric_id": 1, "z_value": cx + noise[0]})
                rows.append({"okato": ok, "year": year, "metric_id": 2, "z_value": cy + noise[1]})
    return pl.DataFrame(rows)


def test_choose_k_picks_three_clusters() -> None:
    """На данных с тремя явными кластерами выбор k по silhouette даёт k=3."""
    fw = _synthetic_features()
    assert choose_k(fw, [2010, 2011], (2, 5), seed=42, algo="kmeans") == 3


def test_year_matrix_shape_and_order() -> None:
    """Матрица года: строки — регионы по okato, столбцы — метрики по metric_id."""
    okato, matrix, metric_ids = year_matrix(_synthetic_features(), 2010)
    assert okato == ["r1", "r2", "r3", "r4", "r5", "r6"]
    assert metric_ids == [1, 2]
    assert matrix.shape == (6, 2)


def test_build_clusters_stable_ids_and_profile() -> None:
    """clusters заполнены, cluster_id стабилен между годами, профиль и метки есть."""
    res = build_clusters(_synthetic_features(), k=3)
    clusters, profile = res.clusters, res.cluster_profile

    assert clusters.height == 6 * 2
    assert set(clusters.columns) == {
        "okato",
        "year",
        "algo",
        "k",
        "cluster_id",
        "cluster_label",
        "silhouette",
        "stability_flag",
    }
    by_region = clusters.group_by("okato").agg(pl.col("cluster_id").n_unique().alias("n"))
    assert by_region["n"].max() == 1  # один регион -> один cluster_id в оба года

    y2010 = clusters.filter(pl.col("year") == 2010)
    y2011 = clusters.filter(pl.col("year") == 2011)
    assert y2010["stability_flag"].null_count() == 6  # опорный год
    assert y2011["stability_flag"][0] == 1.0

    assert profile.height == 3 * 2 * 2  # 3 кластера × 2 метрики × 2 года
    assert clusters["cluster_label"].null_count() == 0


def test_compute_cluster_shap_complete() -> None:
    """cluster_shap: по строке на (okato, year, metric_id), без пропусков, нужные колонки."""
    fw = _synthetic_features()
    res = build_clusters(fw, k=3)
    sh = compute_cluster_shap(fw, res.clusters, seed=42)
    assert set(sh.columns) == {"okato", "year", "metric_id", "shap_value"}
    assert sh.height == 6 * 2 * 2
    assert sh["shap_value"].null_count() == 0


def test_run_typology_returns_three_tables() -> None:
    """run_typology без записи/MLflow возвращает три непустые таблицы типологии."""
    fw = _synthetic_features()
    res = run_typology(fw, write=False, log_mlflow=False)
    assert res.clusters.height == 6 * 2
    assert res.cluster_profile.height > 0
    assert res.cluster_shap.height == 6 * 2 * 2
