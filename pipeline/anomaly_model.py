"""Модель детекции аномалий как применимый сервис.

Таблица `anomalies` помечает пространственные выбросы *внутри каждого года*. Здесь же
обучаем и сохраняем **глобальный** детектор (IsolationForest на всех регионах-годах),
который можно загрузить и применить к произвольному профилю региона, чтобы оценить его
нетипичность на фоне всей панели. Это путь «обучение → сохранение → загрузка → применение»
для второй модели интеллектуального сервиса.

Метрика (для несупервизного детектора согласована как доля выбросов) — anomaly_share.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import polars as pl
from numpy.typing import NDArray
from sklearn.ensemble import IsolationForest

from pipeline.logging_setup import log
from pipeline.models_io import ModelCard, save_model

ANOMALY_MODEL_NAME = "anomaly_detector"


def build_feature_matrix(
    features_wide: pl.DataFrame,
) -> tuple[NDArray[np.float64], list[str]]:
    """Матрица всех регионов-годов: строки — наблюдения, столбцы — метрики ядра (z_value).

    Столбцы упорядочены по возрастанию metric_id (как в year_matrix) для детерминизма.
    """
    wide = features_wide.pivot(on="metric_id", index=["okato", "year"], values="z_value").sort(
        ["year", "okato"]
    )
    feature_cols = sorted((c for c in wide.columns if c not in ("okato", "year")), key=int)
    matrix = wide.select(feature_cols).to_numpy().astype(np.float64)
    return matrix, feature_cols


def train_anomaly_model(
    features_wide: pl.DataFrame,
    *,
    contamination: float = 0.05,
    seed: int = 42,
    save: bool = True,
    models_dir: Any = None,
    log_mlflow: bool = True,
) -> tuple[IsolationForest, ModelCard | None]:
    """Обучить и (по умолчанию) сохранить глобальный детектор аномалий; вернуть модель и карточку.

    Возвращает (модель, карточка). При save=False карточка — None.
    """
    matrix, feature_names = build_feature_matrix(features_wide)
    detector = IsolationForest(contamination=contamination, random_state=seed).fit(matrix)
    anomaly_share = float((detector.predict(matrix) == -1).mean())
    log.info(
        "anomaly_model_trained",
        stage="models",
        n_samples=int(matrix.shape[0]),
        n_features=len(feature_names),
        anomaly_share=round(anomaly_share, 4),
    )

    card: ModelCard | None = None
    if save:
        kwargs: dict[str, Any] = {}
        if models_dir is not None:
            kwargs["models_dir"] = models_dir
        card = save_model(
            detector,
            ANOMALY_MODEL_NAME,
            params={
                "estimator": "IsolationForest",
                "contamination": contamination,
                "seed": seed,
            },
            metrics={"anomaly_share": anomaly_share},
            feature_names=feature_names,
            n_samples=int(matrix.shape[0]),
            log_mlflow=log_mlflow,
            **kwargs,
        )
    return detector, card


def score_anomalies(detector: IsolationForest, matrix: NDArray[np.float64]) -> NDArray[np.float64]:
    """Применить модель: оценка нетипичности (меньше → аномальнее) для профилей регионов."""
    return detector.decision_function(matrix).astype(np.float64)
