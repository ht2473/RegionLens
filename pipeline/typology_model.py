"""Модель типологии как применимый и объяснимый сервис.

Кластеризация (KMeans) присваивает регионам типы по годам. Чтобы тип можно было
*предсказать* для произвольного профиля региона без повторной кластеризации, обучаем
классификатор «признаки региона → тип» на всех годах (метки кластеров уже согласованы
во времени) и сохраняем его. Это и есть путь «обучение → сохранение → загрузка →
применение», а метрика — кросс-валидированная точность воспроизведения типологии.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import polars as pl
from numpy.typing import NDArray
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.model_selection import StratifiedKFold, cross_val_score

from pipeline.logging_setup import log
from pipeline.models_io import ModelCard, save_model

TYPOLOGY_MODEL_NAME = "typology_classifier"


def build_training_matrix(
    features_wide: pl.DataFrame, clusters: pl.DataFrame
) -> tuple[NDArray[np.float64], NDArray[np.int64], list[str]]:
    """Обучающая выборка: z-признаки региона-года → его тип (cluster_id).

    Признаки берутся из features_wide (широкая матрица z_value по метрикам ядра),
    целевая переменная — стабильный cluster_id из таблицы clusters. Столбцы метрик
    упорядочены по возрастанию metric_id (как в year_matrix) для детерминизма.
    """
    wide = features_wide.pivot(on="metric_id", index=["okato", "year"], values="z_value")
    feature_cols = sorted((c for c in wide.columns if c not in ("okato", "year")), key=int)
    joined = wide.join(
        clusters.select(["okato", "year", "cluster_id"]), on=["okato", "year"], how="inner"
    ).sort(["year", "okato"])
    features = joined.select(feature_cols).to_numpy().astype(np.float64)
    target = joined["cluster_id"].to_numpy().astype(np.int64)
    return features, target, feature_cols


def _cv_accuracy(features: NDArray[np.float64], target: NDArray[np.int64], *, seed: int) -> float:
    """Кросс-валидированная точность (стратифицированная 5-кратная, при достатке данных)."""
    _, counts = np.unique(target, return_counts=True)
    n_splits = int(min(5, counts.min()))
    if n_splits < 2:
        return float("nan")
    splitter = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=seed)
    clf = HistGradientBoostingClassifier(random_state=seed)
    scores = cross_val_score(clf, features, target, cv=splitter, scoring="accuracy")
    return float(scores.mean())


def train_typology_model(
    features_wide: pl.DataFrame,
    clusters: pl.DataFrame,
    *,
    seed: int = 42,
    save: bool = True,
    models_dir: Any = None,
    log_mlflow: bool = True,
) -> tuple[HistGradientBoostingClassifier, ModelCard | None]:
    """Обучить и (по умолчанию) сохранить классификатор типологии; вернуть модель и карточку."""
    features, target, feature_names = build_training_matrix(features_wide, clusters)
    accuracy = _cv_accuracy(features, target, seed=seed)

    clf = HistGradientBoostingClassifier(random_state=seed)
    clf.fit(features, target)
    log.info(
        "typology_model_trained",
        stage="models",
        n_samples=int(features.shape[0]),
        n_features=len(feature_names),
        cv_accuracy=None if math.isnan(accuracy) else round(accuracy, 4),
    )

    card: ModelCard | None = None
    if save:
        kwargs: dict[str, Any] = {}
        if models_dir is not None:
            kwargs["models_dir"] = models_dir
        card = save_model(
            clf,
            TYPOLOGY_MODEL_NAME,
            params={"estimator": "HistGradientBoostingClassifier", "seed": seed},
            metrics={"cv_accuracy": accuracy},
            feature_names=feature_names,
            n_samples=int(features.shape[0]),
            log_mlflow=log_mlflow,
            **kwargs,
        )
    return clf, card


def predict_cluster(
    estimator: HistGradientBoostingClassifier, matrix: NDArray[np.float64]
) -> NDArray[np.int64]:
    """Применить модель: предсказать тип (cluster_id) по матрице z-признаков регионов."""
    return estimator.predict(matrix).astype(np.int64)
