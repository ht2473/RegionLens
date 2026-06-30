"""Проверки интернационализации интерфейса (переключение RU/EN).

Исходные строки заданы на русском; каталог ``locale/en`` содержит их перевод.
По умолчанию активен русский язык, переключение выполняется стандартным view
``set_language`` и сохраняется в cookie между запросами тестового клиента.
"""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_default_language_is_russian() -> None:
    """Без явного выбора языка интерфейс отдаётся на русском."""
    html = Client().get("/").content.decode()
    assert "Главная" in html
    assert "Аналитика" in html


def test_language_switcher_is_rendered() -> None:
    """В шапке присутствует переключатель языка с кнопками RU и EN."""
    html = Client().get("/").content.decode()
    assert "lang-switch" in html
    assert ">RU<" in html and ">EN<" in html


def test_switch_to_english_translates_navigation_and_home() -> None:
    """После выбора английского переводятся навигация, главная и подвал."""
    client = Client()
    client.post(reverse("set_language"), {"language": "en", "next": "/"})
    html = client.get("/").content.decode()
    for token in ("Home", "Map", "Indicators", "Analytics", "Convergence"):
        assert token in html
    assert "What you can do" in html
    assert "Master's thesis" in html
    # Подвал переведён полностью — его русский вариант в английской версии отсутствует.
    # (Подписи «хлебных крошек» формируются во вью и переводятся отдельным проходом.)
    assert "ВКР по направлению" not in html


def test_switch_back_to_russian() -> None:
    """Повторное переключение возвращает русский интерфейс."""
    client = Client()
    client.post(reverse("set_language"), {"language": "en", "next": "/"})
    client.post(reverse("set_language"), {"language": "ru", "next": "/"})
    html = client.get("/").content.decode()
    assert "Главная" in html
    assert "Home" not in html
