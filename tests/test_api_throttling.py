"""Rate-limiting публичного API.

Два уровня проверки без зависимости от кэширования настроек DRF:
1) механизм — `AnonRateThrottle` блокирует запрос сверх лимита;
2) подключение — лимиты прописаны в настройках DRF (классы + ставки anon/user).
"""

from __future__ import annotations

import pytest
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

pytestmark = pytest.mark.django_db


class _ThreePerMinute(AnonRateThrottle):
    """Анонимный лимит с фиксированной ставкой 3/мин — для детерминированной проверки."""

    def get_rate(self) -> str:
        return "3/min"


def test_anonymous_throttle_blocks_over_limit() -> None:
    """Первые 3 запроса разрешены, 4-й (сверх лимита) — заблокирован."""
    cache.clear()
    factory = APIRequestFactory()
    view = APIView()
    throttle = _ThreePerMinute()
    verdicts = []
    for _ in range(4):
        drf_request = Request(factory.get("/api/v1/regions/"))
        drf_request.user = AnonymousUser()
        verdicts.append(throttle.allow_request(drf_request, view))
    assert verdicts == [True, True, True, False]


def test_throttling_is_configured() -> None:
    """Лимиты частоты подключены глобально: классы anon/user и их ставки заданы."""
    rest = settings.REST_FRAMEWORK
    classes = rest.get("DEFAULT_THROTTLE_CLASSES", [])
    assert any("AnonRateThrottle" in c for c in classes)
    assert any("UserRateThrottle" in c for c in classes)
    rates = rest.get("DEFAULT_THROTTLE_RATES", {})
    assert rates.get("anon") and rates.get("user")
