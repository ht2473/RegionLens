"""Трекинг ошибок (Sentry/GlitchTip) — опциональная инициализация по SENTRY_DSN.

GlitchTip — self-hosted, Sentry-совместимый приёмник (тот же протокол DSN), поэтому один и тот
же SDK работает и с облачным Sentry, и с локально развёрнутым GlitchTip. Если SENTRY_DSN пуст
(разработка, CI, тесты) — инициализация пропускается: внешних вызовов и накладных расходов нет.
Персональные данные (email/IP) не отправляем (send_default_pii=False). Вынесено из settings.py
отдельной функцией, чтобы поведение можно было покрыть юнит-тестами.
"""

from __future__ import annotations

from typing import Any


def configure_sentry(env: Any) -> bool:
    """Инициализировать Sentry/GlitchTip, если задан SENTRY_DSN.

    env — объект django-environ (вызывается как env("KEY", default=...), есть env.float).
    Возвращает True, если трекинг включён (DSN задан), иначе False (no-op).
    """
    dsn = env("SENTRY_DSN", default="")
    if not dsn:
        return False

    # Импорт внутри ветки: без DSN зависимость даже не трогается.
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration

    sentry_sdk.init(
        dsn=dsn,
        integrations=[DjangoIntegration()],
        environment=env("SENTRY_ENVIRONMENT", default="production"),
        release=env("SENTRY_RELEASE", default=None),
        # Доля трассируемых запросов для performance-мониторинга (0.0 — только ошибки).
        traces_sample_rate=env.float("SENTRY_TRACES_SAMPLE_RATE", default=0.0),
        # Не отправлять персональные данные (email пользователя, IP) во внешний приёмник.
        send_default_pii=False,
    )
    return True
