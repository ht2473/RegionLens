"""Тесты персистентности моделей: сохранение, загрузка, карточка, перечисление."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
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


def test_alias_written_for_known_model(tmp_path: Path) -> None:
    """Для модели из MODEL_ALIASES рядом пишется байтовая копия model1/model2.joblib."""
    import joblib

    from pipeline.models_io import MODEL_ALIASES

    model = _tiny_model()
    card = save_model(
        model,
        "typology_classifier",
        params={"seed": 0},
        metrics={"cv_accuracy": 1.0},
        feature_names=["f0"],
        n_samples=4,
        models_dir=tmp_path,
        log_mlflow=False,
    )
    alias = MODEL_ALIASES["typology_classifier"]
    assert card.alias == alias
    assert (tmp_path / f"{alias}.joblib").exists()  # копия под формальным обозначением
    # карточка под алиасом не создаётся, иначе витрина показала бы модель дважды
    assert not (tmp_path / f"{alias}.json").exists()
    # копия — та же модель (те же предсказания)
    aliased = joblib.load(tmp_path / f"{alias}.joblib")
    sample = np.array([[0.0], [1.0]])
    assert list(aliased.predict(sample)) == list(model.predict(sample))


def test_no_alias_for_unaliased_model(tmp_path: Path) -> None:
    """Модель без обозначения не создаёт лишних артефактов и имеет alias=None."""
    card = save_model(
        _tiny_model(),
        "tiny",
        params={},
        metrics={},
        feature_names=["f0"],
        n_samples=4,
        models_dir=tmp_path,
        log_mlflow=False,
    )
    assert card.alias is None
    assert list(tmp_path.glob("model*.joblib")) == []


def test_list_model_cards_has_no_alias_duplicates(tmp_path: Path) -> None:
    """Витрина перечисляет только канонические модели, без дублей-обозначений."""
    for name in ("typology_classifier", "anomaly_detector"):
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
    assert names == {"typology_classifier", "anomaly_detector"}  # не четыре


def test_list_model_cards_empty_when_dir_missing(tmp_path: Path) -> None:
    """Каталога моделей нет — витрина карточек пустая, без ошибки."""
    assert list_model_cards(models_dir=tmp_path / "does-not-exist") == []


def test_save_model_mlflow_skips_when_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """log_mlflow=True не ломает сохранение, если mlflow недоступен (трекинг best-effort)."""
    import sys

    monkeypatch.setitem(sys.modules, "mlflow", None)  # import mlflow → ImportError
    card = save_model(
        _tiny_model(),
        "tiny",
        params={},
        metrics={},
        feature_names=["f0"],
        n_samples=4,
        models_dir=tmp_path,
        log_mlflow=True,
    )
    assert card.name == "tiny"  # модель сохранена, трекинг тихо пропущен
