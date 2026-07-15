"""Персистентность ML-моделей: сохранение, загрузка и «карточки» моделей.

Обученные модели складываются в каталог `models/` (joblib) вместе с JSON-карточкой
(время обучения, параметры, метрики, признаки) и best-effort логируются в MLflow.
Это делает интеллектуальный сервис управляемым и воспроизводимым: модель обучается,
сохраняется, а затем загружается и применяется к данным без повторного обучения.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pipeline.logging_setup import log

# Импорты sklearn/joblib намеренно отложены внутрь функций сохранения/загрузки: их первичная
# загрузка тяжёлая (секунды), а витрина моделей (`list_model_cards`) читает только JSON-карточки.
# Так открытие страницы «Модели» не платит за импорт ML-стека.

# Каталог моделей (генерируемые артефакты; пересоздаются обучением).
MODELS_DIR = Path("models")

# Формальные обозначения моделей (model1, model2, …) в дополнение к говорящим именам.
# Требование к оформлению ВКР просит артефакты вида model1.*/model2.*; чтобы не терять
# читаемость (код и витрина оперируют говорящими именами), обозначение — это алиас:
# при сохранении модели рядом с `<name>.joblib` пишется байтовая копия `<alias>.joblib`,
# а само соответствие фиксируется в карточке (поле alias) и в docs/MODELS.md.
MODEL_ALIASES: dict[str, str] = {
    "typology_classifier": "model1",
    "anomaly_detector": "model2",
}


@dataclass
class ModelCard:
    """Метаданные обученной модели — для воспроизводимости и витрины в UI."""

    name: str
    created: str  # ISO-8601, UTC
    estimator: str  # класс модели (например, HistGradientBoostingClassifier)
    sklearn_version: str
    params: dict[str, Any]
    metrics: dict[str, float]
    feature_names: list[str]
    n_samples: int
    # Формальное обозначение (model1/model2, …) или None, если алиас не задан. Поле
    # добавлено последним со значением по умолчанию — старые карточки без него читаются.
    alias: str | None = None


def _model_paths(name: str, models_dir: Path) -> tuple[Path, Path]:
    """Пути к файлу модели и карточке для заданного имени."""
    return models_dir / f"{name}.joblib", models_dir / f"{name}.json"


def save_model(
    estimator: Any,
    name: str,
    *,
    params: dict[str, Any],
    metrics: dict[str, float],
    feature_names: list[str],
    n_samples: int,
    models_dir: Path = MODELS_DIR,
    log_mlflow: bool = True,
) -> ModelCard:
    """Сохранить модель в `models/<name>.joblib` и карточку `<name>.json`; best-effort в MLflow.

    Возвращает записанную карточку модели.
    """
    import joblib
    import sklearn

    models_dir.mkdir(parents=True, exist_ok=True)
    card = ModelCard(
        name=name,
        created=datetime.now(UTC).isoformat(timespec="seconds"),
        estimator=type(estimator).__name__,
        sklearn_version=sklearn.__version__,
        params=params,
        metrics=metrics,
        feature_names=feature_names,
        n_samples=n_samples,
        alias=MODEL_ALIASES.get(name),
    )
    model_path, card_path = _model_paths(name, models_dir)
    joblib.dump(estimator, model_path)
    card_path.write_text(json.dumps(asdict(card), ensure_ascii=False, indent=2), encoding="utf-8")
    # Байтовая копия под формальным обозначением (model1.joblib, …). Карточку под алиасом
    # НЕ пишем: витрина перечисляет карточки по *.json и иначе показывала бы модель дважды.
    # Соответствие обозначение↔модель хранится в карточке (alias) и в docs/MODELS.md.
    if card.alias:
        joblib.dump(estimator, models_dir / f"{card.alias}.joblib")
    log.info("model_saved", stage="models", name=name, estimator=card.estimator, metrics=metrics)
    if log_mlflow:
        _log_mlflow(estimator, card)
    return card


def load_model(name: str, *, models_dir: Path = MODELS_DIR) -> tuple[Any, ModelCard]:
    """Загрузить сохранённую модель и её карточку из `models/`."""
    import joblib

    model_path, card_path = _model_paths(name, models_dir)
    estimator = joblib.load(model_path)
    card = ModelCard(**json.loads(card_path.read_text(encoding="utf-8")))
    return estimator, card


def list_model_cards(*, models_dir: Path = MODELS_DIR) -> list[ModelCard]:
    """Карточки всех сохранённых моделей (для витрины в интерфейсе)."""
    if not models_dir.exists():
        return []
    return [
        ModelCard(**json.loads(path.read_text(encoding="utf-8")))
        for path in sorted(models_dir.glob("*.json"))
    ]


def _log_mlflow(estimator: Any, card: ModelCard) -> None:
    """Best-effort регистрация модели, параметров и метрик в MLflow (если установлен)."""
    try:
        import mlflow
        import mlflow.sklearn
    except ImportError:
        return
    try:
        with mlflow.start_run(run_name=f"model_{card.name}"):
            mlflow.log_params(card.params)
            mlflow.log_metrics(card.metrics)
            mlflow.sklearn.log_model(estimator, name=card.name)
    except Exception:  # noqa: BLE001 — трекинг не должен ломать обучение/пайплайн
        log.warning("model_mlflow_skip", stage="models", name=card.name)
