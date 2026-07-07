"""Тесты модели типологии: обучающая матрица, обучение → сохранение → загрузка → применение."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import polars as pl

from pipeline.models_io import load_model
from pipeline.typology_model import (
    TYPOLOGY_MODEL_NAME,
    build_training_matrix,
    predict_cluster,
    train_typology_model,
)


def _synthetic_data(
    n_per_group: int = 40, years: tuple[int, ...] = (2019, 2020, 2021)
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Две разделимые группы регионов по двум метрикам (с лёгким шумом), за несколько лет."""
    rng = np.random.default_rng(0)
    feature_rows: list[dict[str, object]] = []
    cluster_rows: list[dict[str, object]] = []
    index = 0
    for center, cluster in ((-1.0, 0), (1.0, 1)):
        for _ in range(n_per_group):
            okato = f"{index:04d}"
            index += 1
            for year in years:
                for metric_id in (1, 2):
                    z_value = float(center + rng.normal(0, 0.2))
                    feature_rows.append(
                        {"okato": okato, "year": year, "metric_id": metric_id, "z_value": z_value}
                    )
                cluster_rows.append({"okato": okato, "year": year, "cluster_id": cluster})
    return pl.DataFrame(feature_rows), pl.DataFrame(cluster_rows)


def test_build_training_matrix_shapes() -> None:
    """Матрица: 80 регионов × 3 года строк, 2 признака, метки из clusters."""
    features_wide, clusters = _synthetic_data()
    features, target, feature_names = build_training_matrix(features_wide, clusters)
    assert features.shape == (240, 2)
    assert target.shape == (240,)
    assert feature_names == ["1", "2"]


def test_train_save_load_apply(tmp_path: Path) -> None:
    """Полный путь: обучение → сохранение → загрузка → предсказание типа для профиля."""
    features_wide, clusters = _synthetic_data()
    _, card = train_typology_model(
        features_wide, clusters, seed=0, models_dir=tmp_path, log_mlflow=False
    )
    assert card is not None
    assert card.name == TYPOLOGY_MODEL_NAME
    # Данные чётко разделимы — точность воспроизведения типологии высокая.
    assert card.metrics["cv_accuracy"] > 0.9

    loaded, _ = load_model(TYPOLOGY_MODEL_NAME, models_dir=tmp_path)
    assert predict_cluster(loaded, np.array([[-1.0, -1.0]]))[0] == 0
    assert predict_cluster(loaded, np.array([[1.0, 1.0]]))[0] == 1
