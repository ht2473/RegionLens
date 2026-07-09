"""Общая конфигурация тестов.

В проде статику отдаёт WhiteNoise через манифест (хешированные имена, кэш-бастинг),
но манифест существует только после `collectstatic`. Чтобы тесты, рендерящие шаблоны
с тегом `{% static %}`, не требовали предварительной сборки статики, здесь для всех
тестов подменяется хранилище статики на простое (без манифеста).
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def _use_simple_static_storage(settings: pytest.FixtureRequest) -> None:
    """Отключить манифест-хранилище статики на время тестов.

    Также гарантируем существование STATIC_ROOT, чтобы WhiteNoise не предупреждал
    об отсутствующем каталоге статики (в тестах `collectstatic` не выполняется).
    """
    os.makedirs(settings.STATIC_ROOT, exist_ok=True)
    settings.STORAGES = {
        **settings.STORAGES,
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }


@pytest.fixture(autouse=True)
def _reset_throttle_cache() -> None:
    """Сбрасывать счётчики rate-limiting между тестами.

    Лимиты частоты DRF хранятся в кэше по IP. Без сброса быстрые серии запросов в разных
    тестах накапливаются и упираются в лимит. Чистка перед каждым тестом делает прогон
    детерминированным; проверка самого throttling — в отдельном тесте с низким лимитом.
    """
    from django.core.cache import cache

    cache.clear()
