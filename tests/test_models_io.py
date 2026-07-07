"""Тесты персистентности моделей: сохранение, загрузка, карточка, перечисление."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from sklearn.tree import DecisionTreeClassifier

from pipeline.models_io import list_model_cards, load_model, save_model


def _tiny_model() -> DecisionTreeClassifier:
    features = np.array([[0.0], [1.0], [0.0], [1.0]])
    target = np.array([0, 1, 0, 1])
    return DecisionTreeClassifier(random_state=0).fit(features, target)


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    """Сохранённая модель загружается и даёт те же предсказания."""
    model = _tiny_model()
    save_model(
        model,
        "tiny",
        params={"seed": 0},
        metrics={"accuracy": 1.0},
        feature_names=["f0"],
        n_samples=4,
        models_dir=tmp_path,
        log_mlflow=False,
    )
    assert (tmp_path / "tiny.joblib").exists()
    assert (tmp_path / "tiny.json").exists()

    loaded, card = load_model("tiny", models_dir=tmp_path)
    assert card.name == "tiny"
    assert card.metrics["accuracy"] == 1.0
    sample = np.array([[0.0], [1.0]])
    assert list(loaded.predict(sample)) == list(model.predict(sample))


def test_model_card_fields(tmp_path: Path) -> None:
    """Карточка содержит корректные метаданные (класс, признаки, UTC-время, версию sklearn)."""
    card = save_model(
        _tiny_model(),
        "card",
        params={"seed": 0},
        metrics={"accuracy": 1.0},
        feature_names=["f0"],
        n_samples=4,
        models_dir=tmp_path,
        log_mlflow=False,
    )
    assert card.estimator == "DecisionTreeClassifier"
    assert card.feature_names == ["f0"]
    assert card.created.endswith("+00:00")  # ISO-8601 в UTC
    assert card.sklearn_version


def test_list_model_cards(tmp_path: Path) -> None:
    """Перечисление возвращает карточки всех сохранённых моделей."""
    for name in ("m1", "m2"):
        save_model(
            _tiny_model(),
            name,
            params={},
            metrics={},
            feature_names=["f0"],
            n_samples=4,
            models_dir=tmp_path,
            log_mlflow=False,
        )
    names = {card.name for card in list_model_cards(models_dir=tmp_path)}
    assert names == {"m1", "m2"}
