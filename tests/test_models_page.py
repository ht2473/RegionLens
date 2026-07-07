"""Тесты витрины моделей: пустое состояние и отображение карточки обученной модели."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from django.test import Client
from sklearn.tree import DecisionTreeClassifier

from pipeline.models_io import save_model

pytestmark = pytest.mark.django_db


def test_models_page_empty_state(settings: pytest.FixtureRequest, tmp_path: Path) -> None:
    """Без обученных моделей страница открывается и показывает подсказку."""
    settings.MODELS_DIR = str(tmp_path)
    response = Client().get("/models/")
    assert response.status_code == 200
    assert "ещё не обучены" in response.content.decode()


def test_models_page_shows_card(settings: pytest.FixtureRequest, tmp_path: Path) -> None:
    """Карточка модели отображается с человеко-читаемым названием и метрикой в процентах."""
    model = DecisionTreeClassifier(random_state=0).fit(np.array([[0.0], [1.0]]), np.array([0, 1]))
    save_model(
        model,
        "typology_classifier",
        params={"seed": 0},
        metrics={"cv_accuracy": 0.87},
        feature_names=["f0"],
        n_samples=2,
        models_dir=tmp_path,
        log_mlflow=False,
    )
    settings.MODELS_DIR = str(tmp_path)

    response = Client().get("/models/")
    body = response.content.decode()
    assert response.status_code == 200
    assert "Классификатор типологии" in body
    assert "87.0%" in body
