"""Тесты интерактивного применения ML-моделей (эндпоинт /api/models/predict/).

Проверяют полный путь «загрузка сохранённой модели → сбор профиля региона →
предсказание» на реальной (мини) обученной модели и корректную обработку граничных
случаев: неполный профиль (404), отсутствие модели (мягкая деградация).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import duckdb
import numpy as np
import pytest
from core import duck, queries
from django.test import Client
from sklearn.ensemble import IsolationForest
from sklearn.tree import DecisionTreeClassifier

from pipeline.models_io import save_model

pytestmark = pytest.mark.django_db

# Три признака-заглушки: имена совпадут с feature_names сохранённой модели.
FEATURES = ["1404", "1417", "1471"]


@pytest.fixture
def predict_env(tmp_path: Path, settings) -> Iterator[Path]:  # type: ignore[no-untyped-def]
    """Мини-витрина (регион, профиль, метка типа) + каталог моделей во временной папке."""
    path = tmp_path / "predict.duckdb"
    con = duckdb.connect(str(path))
    con.execute(
        "CREATE TABLE region_dim(okato VARCHAR, region_name VARCHAR, included_flag BOOLEAN)"
    )
    con.execute("INSERT INTO region_dim VALUES ('01000000', 'Тестрегион', TRUE)")
    con.execute(
        "CREATE TABLE features_wide(okato VARCHAR, year INTEGER, metric_id VARCHAR, z_value DOUBLE)"
    )
    for metric in FEATURES:
        con.execute("INSERT INTO features_wide VALUES ('01000000', 2024, ?, 0.2)", [metric])
    con.execute(
        "CREATE TABLE clusters(okato VARCHAR, year INTEGER, algo VARCHAR, cluster_id INTEGER, "
        "cluster_label VARCHAR, distance_to_centroid DOUBLE, stability_flag BOOLEAN, k INTEGER)"
    )
    con.execute(
        "INSERT INTO clusters VALUES ('01000000', 2024, 'kmeans', 0, 'Тип А', 0.4, TRUE, 5)"
    )
    con.close()

    settings.DUCKDB_PATH = str(path)
    settings.MODELS_DIR = str(tmp_path / "models")
    duck.reset_connection()
    queries.reset_models_cache()  # изоляция: модели из другого теста не должны кэшироваться
    yield tmp_path
    duck.reset_connection()
    queries.reset_models_cache()


def _train_models(models_dir: Path) -> None:
    """Сохранить мини-модели типологии и аномалий с feature_names = FEATURES."""
    x = np.array([[0.0, 0.0, 0.0], [1.0, 1.0, 1.0]])
    clf = DecisionTreeClassifier(random_state=0).fit(x, np.array([0, 1]))
    save_model(
        clf,
        "typology_classifier",
        params={},
        metrics={"cv_accuracy": 0.9},
        feature_names=FEATURES,
        n_samples=2,
        models_dir=models_dir,
        log_mlflow=False,
    )
    iso = IsolationForest(random_state=0, n_estimators=10).fit(x)
    save_model(
        iso,
        "anomaly_detector",
        params={},
        metrics={"anomaly_share": 0.1},
        feature_names=FEATURES,
        n_samples=2,
        models_dir=models_dir,
        log_mlflow=False,
    )


def test_predict_returns_typology_and_anomaly(predict_env: Path) -> None:
    """Обе модели применяются к профилю региона и возвращают осмысленный результат."""
    _train_models(predict_env / "models")
    resp = Client().get("/api/models/predict/?okato=01000000&year=2024")
    assert resp.status_code == 200
    body = resp.json()
    assert body["region_name"] == "Тестрегион"
    assert body["typology"]["cluster_id"] == 0
    assert body["typology"]["cluster_label"] == "Тип А"
    assert body["anomaly"]["is_outlier"] in (True, False)
    assert isinstance(body["anomaly"]["score"], float)


def test_predict_unknown_region_404(predict_env: Path) -> None:
    """Несуществующий регион → 404 с понятным сообщением."""
    _train_models(predict_env / "models")
    resp = Client().get("/api/models/predict/?okato=99999999&year=2024")
    assert resp.status_code == 404


def test_predict_incomplete_profile_404(predict_env: Path) -> None:
    """Год без профиля региона → 404 (модель применять некорректно)."""
    _train_models(predict_env / "models")
    resp = Client().get("/api/models/predict/?okato=01000000&year=2011")
    assert resp.status_code == 404


def test_predict_missing_models_soft_degrades(predict_env: Path) -> None:
    """Без сохранённых моделей поля предсказаний равны None (мягкая деградация), не 500."""
    # Модели не обучаем: каталог моделей пуст.
    resp = Client().get("/api/models/predict/?okato=01000000&year=2024")
    assert resp.status_code == 200
    body = resp.json()
    assert body["typology"] is None
    assert body["anomaly"] is None


def test_predict_requires_okato(predict_env: Path) -> None:
    """Без параметра okato → 400."""
    resp = Client().get("/api/models/predict/?year=2024")
    assert resp.status_code == 400
