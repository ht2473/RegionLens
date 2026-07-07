"""Тесты модели аномалий: матрица признаков, обучение → сохранение → загрузка → применение."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import polars as pl

from pipeline.anomaly_model import (
    ANOMALY_MODEL_NAME,
    build_feature_matrix,
    score_anomalies,
    train_anomaly_model,
)
from pipeline.models_io import load_model


def _synthetic_data(n_inliers: int = 90, n_outliers: int = 10) -> pl.DataFrame:
    """Плотное ядро типичных регионов + небольшая доля явных выбросов (по двум метрикам)."""
    rng = np.random.default_rng(0)
    rows: list[dict[str, object]] = []
    index = 0
    for center, count in ((0.0, n_inliers), (5.0, n_outliers)):
        for _ in range(count):
            okato = f"{index:04d}"
            index += 1
            for metric_id in (1, 2):
                rows.append(
                    {
                        "okato": okato,
                        "year": 2021,
                        "metric_id": metric_id,
                        "z_value": float(rng.normal(center, 0.3)),
                    }
                )
    return pl.DataFrame(rows)


def test_build_feature_matrix_shapes() -> None:
    """Матрица: 100 регионов-годов × 2 признака, столбцы по возрастанию metric_id."""
    matrix, feature_names = build_feature_matrix(_synthetic_data())
    assert matrix.shape == (100, 2)
    assert feature_names == ["1", "2"]


def test_train_save_load_apply(tmp_path: Path) -> None:
    """Полный путь: обучение → сохранение → загрузка → оценка нетипичности профиля."""
    features_wide = _synthetic_data()
    _, card = train_anomaly_model(
        features_wide, contamination=0.1, seed=0, models_dir=tmp_path, log_mlflow=False
    )
    assert card is not None
    assert card.name == ANOMALY_MODEL_NAME
    assert 0.05 <= card.metrics["anomaly_share"] <= 0.2

    loaded, _ = load_model(ANOMALY_MODEL_NAME, models_dir=tmp_path)
    inlier_score = score_anomalies(loaded, np.array([[0.0, 0.0]]))[0]
    outlier_score = score_anomalies(loaded, np.array([[5.0, 5.0]]))[0]
    # Меньше — аномальнее: у явного выброса оценка ниже, чем у типичного профиля.
    assert outlier_score < inlier_score
