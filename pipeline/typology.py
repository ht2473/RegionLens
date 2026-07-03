"""Типология регионов: кластеризация по годам со стабильными во
времени метками.

Из features_wide (z_value) для каждого года окна собираем матрицу (регионы × ядро),
кластеризуем (KMeans/Ward), выбираем единое k для всех лет, согласуем метки между
соседними годами венгерским алгоритмом (стабильный cluster_id), считаем профили и
осмысленные метки кластеров. Результат — таблицы clusters и cluster_profile (в памяти).

Дальнейшие шаги — SHAP-объяснение (cluster_shap), MLflow и запись таблиц в DuckDB.

Параметры — из config/analytics.yaml (clustering); имена метрик ядра — из indicators.yaml.
"""

from dataclasses import dataclass
from typing import Any, cast

import numpy as np
import polars as pl
import shap
from scipy.optimize import linear_sum_assignment
from sklearn.cluster import AgglomerativeClustering, KMeans
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import (
    calinski_harabasz_score,
    davies_bouldin_score,
    silhouette_score,
)

from pipeline.config import load_config
from pipeline.duck import write_table
from pipeline.logging_setup import log


@dataclass
class TypologyTables:
    """Результат кластеризации — вход для этапа объяснения (SHAP/запись)."""

    # okato, year, algo, k, cluster_id, cluster_label, silhouette, stability_flag,
    # distance_to_centroid (A1)
    clusters: pl.DataFrame
    cluster_profile: pl.DataFrame  # algo, k, year, cluster_id, metric_id, mean_z


def year_matrix(features_wide: pl.DataFrame, year: int) -> tuple[list[str], np.ndarray, list[int]]:
    """Матрица года: строки — регионы (по okato), столбцы — метрики ядра (по metric_id), z_value.

    features_wide уже без пропусков и только по включённым регионам, поэтому матрица плотная.
    Возвращает (список okato в порядке строк, X, список metric_id в порядке столбцов).
    """
    fy = features_wide.filter(pl.col("year") == year)
    wide = fy.pivot(on="metric_id", index="okato", values="z_value").sort("okato")
    value_cols = sorted((c for c in wide.columns if c != "okato"), key=int)
    metric_ids = [int(c) for c in value_cols]
    matrix = wide.select(value_cols).to_numpy()
    okato = wide["okato"].to_list()
    return okato, matrix, metric_ids


def fit_labels(matrix: np.ndarray, k: int, algo: str, seed: int) -> np.ndarray:
    """Разбить на k кластеров выбранным алгоритмом (детерминированно по сиду)."""
    if algo == "ward":
        return AgglomerativeClustering(n_clusters=k, linkage="ward").fit_predict(matrix)
    return KMeans(n_clusters=k, random_state=seed, n_init=10).fit_predict(matrix)


def cluster_quality(matrix: np.ndarray, labels: np.ndarray) -> dict[str, float]:
    """Метрики качества разбиения: silhouette (↑), Davies-Bouldin (↓), Calinski-Harabasz (↑)."""
    if len(set(labels.tolist())) < 2:
        return {
            "silhouette": float("nan"),
            "davies_bouldin": float("nan"),
            "calinski_harabasz": float("nan"),
        }
    return {
        "silhouette": float(silhouette_score(matrix, labels)),
        "davies_bouldin": float(davies_bouldin_score(matrix, labels)),
        "calinski_harabasz": float(calinski_harabasz_score(matrix, labels)),
    }


def choose_k(
    features_wide: pl.DataFrame, years: list[int], k_range: tuple[int, int], seed: int, algo: str
) -> int:
    """Единое k для всех лет: максимум среднего по годам silhouette в диапазоне k_range.

    Единое k обеспечивает сопоставимость типологии между годами (одинаковое число типов).
    """
    matrices = [year_matrix(features_wide, y)[1] for y in years]
    # silhouette требует 2 <= k <= n_samples-1; ограничиваем верх по самому малому году
    min_samples = min(m.shape[0] for m in matrices)
    k_max = min(k_range[1], min_samples - 1)
    best_k, best_score = k_range[0], float("-inf")
    for k in range(k_range[0], k_max + 1):
        sils = [silhouette_score(m, fit_labels(m, k, algo, seed)) for m in matrices]
        mean_sil = float(np.mean(sils))
        log.info("choose_k_candidate", stage="typology", k=k, mean_silhouette=round(mean_sil, 4))
        if mean_sil > best_score:
            best_k, best_score = k, mean_sil
    log.info("choose_k", stage="typology", chosen_k=best_k, mean_silhouette=round(best_score, 4))
    return best_k


def align_labels(
    prev_labels: np.ndarray,
    prev_okato: list[str],
    cur_labels: np.ndarray,
    cur_okato: list[str],
    k: int,
) -> np.ndarray:
    """Согласовать метки текущего года с предыдущим (венгерский алгоритм по пересечению).

    Строим матрицу совпадений членства между кластерами t-1 и t по общим регионам,
    максимизируем суммарное пересечение (linear_sum_assignment) и переименовываем метки t.
    Так cluster_id остаётся стабильным во времени (тип «богатые регионы» не меняет номер).
    """
    prev = dict(zip(prev_okato, prev_labels.tolist(), strict=True))
    cur = dict(zip(cur_okato, cur_labels.tolist(), strict=True))
    overlap = np.zeros((k, k))
    for okato in set(cur) & set(prev):
        overlap[prev[okato], cur[okato]] += 1
    rows, cols = linear_sum_assignment(-overlap)  # максимизируем пересечение
    remap = {int(c): int(r) for r, c in zip(rows, cols, strict=True)}
    return np.array([remap[int(label)] for label in cur_labels.tolist()])


def centroid_distances(matrix: np.ndarray, labels: np.ndarray) -> np.ndarray:
    """Евклидово расстояние каждого региона до центра (среднего) своего кластера (A1).

    Центроиды считаются эмпирически по фактическим (уже согласованным) меткам — поэтому
    мера корректна и для KMeans, и для Ward, и после венгерского переименования меток.
    Интерпретация: «насколько типичен регион для своего типа» — малое расстояние = ядро
    типа, большое = пограничный/нетипичный регион. Это мера типичности/пограничности,
    НЕ вероятность перехода в другой тип.
    """
    distances = np.zeros(matrix.shape[0], dtype=float)
    for label in np.unique(labels):
        mask = labels == label
        centroid = matrix[mask].mean(axis=0)
        distances[mask] = np.linalg.norm(matrix[mask] - centroid, axis=1)
    return distances


def _cluster_labels(profile: pl.DataFrame, names: dict[int, str], top: int = 2) -> pl.DataFrame:
    """Метка кластера: top-N метрик профиля по |mean_z| со знаком (↑ выше / ↓ ниже среднего)."""
    rows: list[dict[str, Any]] = []
    keys = profile.select(["year", "cluster_id"]).unique().sort(["year", "cluster_id"])
    for key in keys.to_dicts():
        sub = (
            profile.filter(
                (pl.col("year") == key["year"]) & (pl.col("cluster_id") == key["cluster_id"])
            )
            .with_columns(pl.col("mean_z").abs().alias("_abs"))
            .sort("_abs", descending=True)
            .head(top)
        )
        parts = []
        for r in sub.to_dicts():
            arrow = "↑" if r["mean_z"] >= 0 else "↓"
            parts.append(f"{arrow}{names.get(int(r['metric_id']), str(r['metric_id']))}")
        rows.append(
            {
                "year": key["year"],
                "cluster_id": key["cluster_id"],
                "cluster_label": ", ".join(parts),
            }
        )
    return pl.DataFrame(rows)


def build_clusters(features_wide: pl.DataFrame, *, k: int | None = None) -> TypologyTables:
    """Кластеризация целиком: по годам кластеризуем, согласуем метки, считаем профили и метки.

    k берётся из аргумента (для тестов) или config (chosen_k), иначе выбирается по silhouette.
    Алгоритм и сид — из config/analytics.yaml (clustering). Имена метрик — из indicators.yaml.
    """
    analytics = load_config("analytics")
    clu = analytics.get("clustering") or {}
    seed = int(clu.get("seed", 42))
    algo = str(clu.get("algo", "kmeans"))
    k_range = tuple(clu.get("k_range", [3, 8]))

    # годы берём из самих данных (features_wide уже ограничен окном анализа)
    years = sorted(int(y) for y in features_wide["year"].unique().to_list())

    if k is None:
        k = (
            int(clu["chosen_k"])
            if clu.get("chosen_k")
            else choose_k(features_wide, years, (int(k_range[0]), int(k_range[1])), seed, algo)
        )

    indicators = load_config("indicators")
    names = {int(c["metric_id"]): str(c["name"]) for c in (indicators.get("core") or [])}

    cluster_rows: list[dict[str, Any]] = []
    profile_frames: list[pl.DataFrame] = []
    prev_labels: np.ndarray | None = None
    prev_okato: list[str] | None = None
    prev_dict: dict[str, int] = {}

    for year in years:
        okato, matrix, _ = year_matrix(features_wide, year)
        labels = fit_labels(matrix, k, algo, seed)
        if prev_labels is not None and prev_okato is not None:
            labels = align_labels(prev_labels, prev_okato, labels, okato, k)
            same: float | None = float(
                np.mean([labels[i] == prev_dict[okato[i]] for i in range(len(okato))])
            )
        else:
            same = None  # первый год окна — опорный, год-к-году не с чем сравнивать
        sil = cluster_quality(matrix, labels)["silhouette"]
        distances = centroid_distances(matrix, labels)  # A1: типичность/пограничность

        for i, ok in enumerate(okato):
            cluster_rows.append(
                {
                    "okato": ok,
                    "year": year,
                    "algo": algo,
                    "k": k,
                    "cluster_id": int(labels[i]),
                    "silhouette": sil,
                    "stability_flag": same,
                    "distance_to_centroid": float(distances[i]),
                }
            )
        ydf = pl.DataFrame({"okato": okato, "cluster_id": labels.tolist()}).join(
            features_wide.filter(pl.col("year") == year).select(["okato", "metric_id", "z_value"]),
            on="okato",
        )
        prof = (
            ydf.group_by(["cluster_id", "metric_id"])
            .agg(pl.col("z_value").mean().alias("mean_z"))
            .with_columns(
                pl.lit(year).alias("year"), pl.lit(algo).alias("algo"), pl.lit(k).alias("k")
            )
        )
        profile_frames.append(prof)
        prev_labels, prev_okato = labels, okato
        prev_dict = dict(zip(okato, labels.tolist(), strict=True))

    profile = pl.concat(profile_frames).select(
        ["algo", "k", "year", "cluster_id", "metric_id", "mean_z"]
    )
    labels_df = _cluster_labels(profile, names)
    clusters = (
        pl.DataFrame(cluster_rows)
        .join(labels_df, on=["year", "cluster_id"], how="left")
        .select(
            [
                "okato",
                "year",
                "algo",
                "k",
                "cluster_id",
                "cluster_label",
                "silhouette",
                "stability_flag",
                "distance_to_centroid",
            ]
        )
        .sort(["year", "okato"])
    )
    log.info(
        "clusters_built",
        stage="typology",
        k=k,
        algo=algo,
        years=f"{years[0]}-{years[-1]}",
        rows=clusters.height,
    )
    return TypologyTables(clusters=clusters, cluster_profile=profile)


# --------------------------------------------------------------------------- #
# Объяснение и запись: SHAP-объяснение принадлежности, MLflow, запись таблиц
# --------------------------------------------------------------------------- #
def _shap_to_class_array(shap_values: object, n_samples: int, n_features: int) -> np.ndarray:
    """Привести вывод shap к форме (n_samples, n_features, n_classes) для разных версий shap."""
    if isinstance(shap_values, list):  # старый формат: список матриц по классам
        return np.stack(shap_values, axis=-1)
    arr = np.asarray(shap_values)
    if arr.ndim == 3:  # новый формат: уже (n_samples, n_features, n_classes)
        return arr
    return arr.reshape(n_samples, n_features, 1)  # бинарный случай


def compute_cluster_shap(
    features_wide: pl.DataFrame, clusters: pl.DataFrame, *, seed: int = 42
) -> pl.DataFrame:
    """SHAP-объяснение принадлежности: вклад каждой метрики в попадание региона в его тип.

    По каждому году обучаем бустинг предсказывать СТАБИЛЬНЫЙ cluster_id (из clusters) по
    признакам ядра и берём SHAP-значения для фактического класса региона. Результат —
    cluster_shap(okato, year, metric_id, shap_value).
    """
    rows: list[dict[str, Any]] = []
    years = sorted(int(y) for y in features_wide["year"].unique().to_list())
    for year in years:
        okato, matrix, metric_ids = year_matrix(features_wide, year)
        lab = clusters.filter(pl.col("year") == year).sort("okato")
        labels = np.array(lab["cluster_id"].to_list())
        clf = HistGradientBoostingClassifier(random_state=seed).fit(matrix, labels)
        sv = _shap_to_class_array(
            shap.TreeExplainer(clf).shap_values(matrix), len(okato), len(metric_ids)
        )
        classes = clf.classes_.tolist()
        for i, ok in enumerate(okato):
            class_idx = classes.index(int(labels[i]))
            for j, mid in enumerate(metric_ids):
                rows.append(
                    {
                        "okato": ok,
                        "year": year,
                        "metric_id": mid,
                        "shap_value": float(sv[i, j, class_idx]),
                    }
                )
    shap_df = pl.DataFrame(rows)
    log.info("cluster_shap_built", stage="typology", rows=shap_df.height, years=len(years))
    return shap_df


def _log_mlflow(clusters: pl.DataFrame, algo: str, k: int) -> None:
    """Best-effort логирование метрик типологии в MLflow (если установлен)."""
    try:
        import mlflow
    except ImportError:
        log.warning("mlflow_skip", stage="typology", reason="mlflow не установлен")
        return
    sil = clusters.group_by("year").agg(pl.col("silhouette").first())["silhouette"].mean()
    stab = (
        clusters.filter(pl.col("stability_flag").is_not_null())
        .group_by("year")
        .agg(pl.col("stability_flag").first())["stability_flag"]
        .mean()
    )
    with mlflow.start_run(run_name=f"typology_{algo}_k{k}"):
        mlflow.log_param("algo", algo)
        mlflow.log_param("k", k)
        mlflow.log_metric("silhouette_mean", cast(float, sil) if sil is not None else 0.0)
        mlflow.log_metric("stability_mean", cast(float, stab) if stab is not None else 0.0)


@dataclass
class TypologyResult:
    """Итог: три таблицы типологии."""

    clusters: pl.DataFrame
    cluster_profile: pl.DataFrame
    cluster_shap: pl.DataFrame


def run_typology(
    features_wide: pl.DataFrame,
    *,
    duckdb_path: str = "data/regionlens.duckdb",
    write: bool = True,
    log_mlflow: bool = True,
) -> TypologyResult:
    """Типология целиком: кластеризация → объяснение (SHAP) → запись таблиц + MLflow."""
    tables = build_clusters(features_wide)
    seed = int((load_config("analytics").get("clustering") or {}).get("seed", 42))
    shap_df = compute_cluster_shap(features_wide, tables.clusters, seed=seed)
    algo = tables.clusters["algo"][0]
    k = int(tables.clusters["k"][0])
    if log_mlflow:
        _log_mlflow(tables.clusters, algo, k)
    if write:
        write_table(duckdb_path, "clusters", tables.clusters)
        write_table(duckdb_path, "cluster_profile", tables.cluster_profile)
        write_table(duckdb_path, "cluster_shap", shap_df)
        log.info(
            "typology_written",
            stage="typology",
            path=duckdb_path,
            clusters=tables.clusters.height,
            profile=tables.cluster_profile.height,
            shap=shap_df.height,
        )
    return TypologyResult(
        clusters=tables.clusters, cluster_profile=tables.cluster_profile, cluster_shap=shap_df
    )


if __name__ == "__main__":
    from pipeline.duck import read_table

    fw = read_table("data/regionlens.duckdb", "features_wide")
    run_typology(fw)
