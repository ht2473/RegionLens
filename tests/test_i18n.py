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


def test_about_pages_translated_to_english() -> None:
    """Раздел «О проекте» (методология, данные, справка) переведён на английский."""
    client = Client()
    client.post(reverse("set_language"), {"language": "en", "next": "/"})
    methodology = client.get("/methodology/").content.decode()
    assert "How it works" in methodology
    assert "Data harmonisation" in methodology
    assert "Гармонизация данных" not in methodology
    data = client.get("/data/").content.decode()
    assert "Source and coverage" in data
    assert "non-overlapping Russian regions" in data
    assert "Источник и охват" not in data
    help_page = client.get("/help/").content.decode()
    assert "Notation" in help_page
    assert "Обозначения" not in help_page


def test_breadcrumbs_translated_to_english() -> None:
    """Подписи «хлебных крошек» формируются во вью и переводятся вместе с интерфейсом."""
    client = Client()
    client.post(reverse("set_language"), {"language": "en", "next": "/"})
    html = client.get("/data/").content.decode()
    assert "Home" in html and "Data" in html
    assert "Главная" not in html
