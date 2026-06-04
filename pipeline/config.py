"""Загрузка YAML-конфигов (config/*.yaml). Без хардкода: значения берём отсюда."""

from pathlib import Path
from typing import Any

import yaml

#: Каталог конфигов относительно корня репозитория (конвейер запускается из корня).
CONFIG_DIR = Path("config")


def load_yaml(path: str | Path) -> dict[str, Any]:
    """Прочитать YAML-файл и вернуть его как словарь.

    Исключения:
        FileNotFoundError: файла нет;
        ValueError: содержимое не является YAML-объектом (словарём).
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Конфиг не найден: {p}")
    with p.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"Ожидался YAML-объект (словарь) в {p}, получено: {type(data).__name__}")
    return data


def load_config(name: str) -> dict[str, Any]:
    """Загрузить config/<name>.yaml (например, load_config('sources'))."""
    return load_yaml(CONFIG_DIR / f"{name}.yaml")
