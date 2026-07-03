"""Smoke-тесты: импорт пакетов, настройка логирования, загрузка настроек Django."""

from __future__ import annotations

from typing import Any


def test_pipeline_imports() -> None:
    """Пакет конвейера импортируется, логирование настраивается без ошибок."""
    import pipeline
    from pipeline import logging_setup

    logging_setup.configure_logging()
    assert pipeline.__name__ == "pipeline"
    assert logging_setup.log is not None


def test_run_all_plan_is_wired() -> None:
    """Оркестратор конвейера собран: план непуст, select_stages() возвращает весь план."""
    from pipeline.run_all import STAGES, select_stages

    assert len(STAGES) >= 7
    assert [s.name for s in select_stages()] == [s.name for s in STAGES]


def test_django_settings_load(settings: Any) -> None:
    """Настройки Django загружаются; ключевые приложения подключены."""
    assert "core" in settings.INSTALLED_APPS
    assert "rest_framework" in settings.INSTALLED_APPS
    assert settings.DUCKDB_PATH
