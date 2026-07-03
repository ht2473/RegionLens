"""Тесты безопасности боевых настроек.

Проверяем поведение блока в `config/settings.py`:
- в боевом режиме (DEBUG=False) строгие флаги ВКЛЮЧАЮТСЯ;
- в dev (DEBUG=True) они расслаблены, чтобы `runserver` работал по HTTP;
- предохранитель не даёт остаться на дефолтном небезопасном ключе в проде.

Настройки вычисляются на этапе импорта, поэтому модуль перечитывается с подменённым
окружением (importlib.reload под mock.patch.dict). Django читает значения в свой
объект `settings` один раз при старте — перезагрузка модуля на него не влияет, поэтому
другие тесты не затрагиваются; после каждого теста модуль возвращается в исходное
состояние autouse-фикстурой.
"""

from __future__ import annotations

import contextlib
import importlib
import os
from collections.abc import Iterator
from typing import Any
from unittest import mock

import config.settings as settings_mod
import pytest
from django.core.exceptions import ImproperlyConfigured

# Прод-подобное окружение. Ключ — длинный и не дефолтный, иначе сработает предохранитель.
_PROD_ENV = {
    "DJANGO_DEBUG": "False",
    "DJANGO_SECRET_KEY": "k7-Region_Lens-pR0d-2026-" + "abcDEF1234567890" * 3,
    "DJANGO_ALLOWED_HOSTS": "regionlens.example.com",
}
_DEV_ENV = {"DJANGO_DEBUG": "True"}


@contextlib.contextmanager
def _settings_with(env: dict[str, str]) -> Iterator[Any]:
    """Перечитать модуль настроек с подменённым окружением; вернуть перезагруженный модуль."""
    with mock.patch.dict(os.environ, env, clear=False):
        importlib.reload(settings_mod)
        yield settings_mod


@pytest.fixture(autouse=True)
def _restore_settings() -> Iterator[None]:
    """Вернуть модуль настроек в исходное (процессное) состояние после теста."""
    yield
    importlib.reload(settings_mod)


def test_prod_enables_secure_flags() -> None:
    """В боевом режиме включаются HTTPS-редирект, secure-cookies и HSTS."""
    with _settings_with(_PROD_ENV) as s:
        assert s.DEBUG is False
        assert s.SECURE_SSL_REDIRECT is True
        assert s.SESSION_COOKIE_SECURE is True
        assert s.CSRF_COOKIE_SECURE is True
        assert s.SECURE_HSTS_SECONDS == 31_536_000
        assert s.SECURE_HSTS_INCLUDE_SUBDOMAINS is True
        assert s.SECURE_HSTS_PRELOAD is True
        # Доверие прокси и неизменные защитные заголовки.
        assert s.SECURE_PROXY_SSL_HEADER == ("HTTP_X_FORWARDED_PROTO", "https")
        assert s.SECURE_CONTENT_TYPE_NOSNIFF is True
        assert s.X_FRAME_OPTIONS == "DENY"


def test_dev_keeps_flags_relaxed() -> None:
    """В dev строгие флаги выключены — локальная разработка идёт по HTTP."""
    with _settings_with(_DEV_ENV) as s:
        assert s.DEBUG is True
        assert s.SECURE_SSL_REDIRECT is False
        assert s.SESSION_COOKIE_SECURE is False
        assert s.CSRF_COOKIE_SECURE is False
        assert s.SECURE_HSTS_SECONDS == 0


def test_security_headers_on_in_both_modes() -> None:
    """Анти-sniffing/анти-кликджекинг включены и в dev — это не мешает разработке."""
    with _settings_with(_DEV_ENV) as s:
        assert s.SECURE_CONTENT_TYPE_NOSNIFF is True
        assert s.X_FRAME_OPTIONS == "DENY"
        assert s.SESSION_COOKIE_HTTPONLY is True


def test_prod_requires_real_secret_key() -> None:
    """Боевой режим с дефолтным ключом останавливает запуск (предохранитель)."""
    bad_env = {"DJANGO_DEBUG": "False", "DJANGO_SECRET_KEY": "dev-insecure-change-me"}
    with mock.patch.dict(os.environ, bad_env, clear=False), pytest.raises(ImproperlyConfigured):
        importlib.reload(settings_mod)
