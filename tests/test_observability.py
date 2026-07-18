"""Тесты трекинга ошибок (Sentry/GlitchTip): опциональность и безопасная конфигурация."""

from __future__ import annotations

from typing import Any

import pytest
from config.observability import configure_sentry


class _FakeEnv:
    """Заглушка django-environ: env("KEY", default=...) и env.float(...)."""

    def __init__(self, values: dict[str, str]) -> None:
        self._values = values

    def __call__(self, key: str, default: Any = None) -> Any:
        return self._values.get(key, default)

    def float(self, key: str, default: float = 0.0) -> float:
        return float(self._values.get(key, default))


def test_disabled_without_dsn() -> None:
    """Без SENTRY_DSN трекинг выключен и SDK не инициализируется."""
    assert configure_sentry(_FakeEnv({})) is False
    assert configure_sentry(_FakeEnv({"SENTRY_DSN": ""})) is False


def test_enabled_with_dsn_sets_safe_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """С SENTRY_DSN инициализация вызывается с нужным DSN, без PII и с заданным traces rate."""
    import sentry_sdk

    captured: dict[str, Any] = {}
    monkeypatch.setattr(sentry_sdk, "init", lambda **kw: captured.update(kw))

    enabled = configure_sentry(
        _FakeEnv(
            {
                "SENTRY_DSN": "https://key@example.com/1",
                "SENTRY_ENVIRONMENT": "staging",
                "SENTRY_TRACES_SAMPLE_RATE": "0.25",
            }
        )
    )
    assert enabled is True
    assert captured["dsn"] == "https://key@example.com/1"
    assert captured["environment"] == "staging"
    assert captured["traces_sample_rate"] == 0.25
    assert captured["send_default_pii"] is False  # персональные данные не отправляем
    # интеграция Django подключена
    from sentry_sdk.integrations.django import DjangoIntegration

    assert any(isinstance(i, DjangoIntegration) for i in captured["integrations"])
