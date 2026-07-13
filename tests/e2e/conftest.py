"""Браузерные (e2e) сценарии на Playwright.

Зачем отдельный слой: серверные тесты проверяют HTML-ответ, но не рендер и поведение
в браузере — регрессии интерфейса (горячие клавиши при другой раскладке, скачущая
высота шапки, «застывшая» тема карты, перекрытие подсказок графиков) для них невидимы.
Сценарии ниже фиксируют наблюдаемое поведение страницы против живого сервера.

Запуск локально:
    python -m playwright install chromium   # один раз, скачивает браузер
    pytest -m e2e

По умолчанию e2e исключены из общего прогона (addopts: -m "not e2e"), чтобы юнит-тесты
оставались быстрыми и не требовали установленных браузеров.
"""

from __future__ import annotations

import os

# Playwright (sync API) исполняется внутри событийного цикла; Django распознаёт такой
# контекст как асинхронный и без флага блокирует обращения к ORM из тестовых фикстур
# (создание пользователя и т.п.). Флаг безопасен: данные каждого теста изолированы.
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")

import pytest
from playwright.sync_api import ConsoleMessage, Error, Page


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args: dict) -> dict:
    """Единые параметры контекста браузера для всех сценариев.

    Русская локаль включает переводы строк из djangojs-каталога (селекторы вида
    [data-title="Скачать SVG"] детерминированы), а фиксированный десктопный вьюпорт
    делает измерения геометрии (высота шапки, переполнение полей) воспроизводимыми.
    """
    return {
        **browser_context_args,
        "viewport": {"width": 1440, "height": 900},
        "locale": "ru-RU",
    }


@pytest.fixture
def strict_page(page: Page):
    """Страница, падающая при любой JS-ошибке.

    Необработанное исключение (pageerror) или console.error — это дефект, даже если
    страница внешне выглядит целой: именно так «тихо» отсутствовал тег Plotly на
    странице сценариев. Фильтруется только шум 404 по favicon — он не относится к
    прикладному коду.
    """
    errors: list[str] = []

    def on_pageerror(exc: Error) -> None:
        errors.append(f"pageerror: {exc}")

    def on_console(msg: ConsoleMessage) -> None:
        if msg.type == "error" and "favicon" not in msg.text.lower():
            errors.append(f"console.error: {msg.text}")

    page.on("pageerror", on_pageerror)
    page.on("console", on_console)
    yield page
    assert not errors, "JS-ошибки на странице:\n" + "\n".join(errors)


@pytest.fixture
def user_credentials(django_user_model) -> dict[str, str]:
    """Тестовый пользователь для сценариев, требующих входа."""
    creds = {"username": "e2e_user", "password": "Sl0zhn1y-parol-e2e"}
    django_user_model.objects.create_user(**creds)
    return creds


def login(page: Page, base_url: str, creds: dict[str, str]) -> None:
    """Войти через реальную форму /accounts/login/ (а не через подмену сессии).

    Прохождение полного пути — CSRF-токен, POST формы, редирект — само по себе
    проверяет работоспособность аутентификации в браузере.
    """
    page.goto(base_url + "/accounts/login/")
    page.fill('input[name="username"]', creds["username"])
    page.fill('input[name="password"]', creds["password"])
    # Кнопка отправки берётся строго внутри формы входа (форма, содержащая поле пароля):
    # в шапке страницы есть другая POST-форма — переключатель языка с двумя кнопками
    # type="submit" (RU/EN), стоящая в DOM раньше. Неквалифицированный селектор
    # `form button[type=submit]` кликал по ней и вместо входа отправлял смену языка.
    page.click('form:has(input[name="password"]) button[type="submit"]')
    # LOGIN_REDIRECT_URL = "/": дожидаемся ухода со страницы логина.
    page.wait_for_url(base_url + "/")
