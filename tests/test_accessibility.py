"""Базовые проверки доступности (WCAG): пропуск навигации, ориентир main, атрибут языка."""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_skip_link_and_main_landmark_present() -> None:
    """На странице есть ссылка «Перейти к содержимому» и ориентир <main id="main">."""
    body = Client().get("/").content.decode()
    assert 'class="skip-link"' in body
    assert 'href="#main"' in body
    assert '<main id="main"' in body


def test_html_lang_is_russian_by_default() -> None:
    body = Client().get("/").content.decode()
    assert '<html lang="ru"' in body


def test_html_lang_reflects_english_selection() -> None:
    """Атрибут языка отражает выбранную локаль (WCAG 3.1.1)."""
    client = Client()
    client.post(reverse("set_language"), {"language": "en", "next": "/"})
    body = client.get("/").content.decode()
    assert '<html lang="en"' in body


def test_home_has_onboarding_banner() -> None:
    """Главная содержит приветственный онбординг-баннер (скрыт до показа скриптом)."""
    body = Client().get("/").content.decode()
    assert 'id="rl-onboarding"' in body


def test_empty_state_component_on_empty_exports(django_user_model) -> None:
    """Страница выгрузок без данных показывает единый компонент пустого состояния."""
    user = django_user_model.objects.create_user(username="empty-user", password="x")
    client = Client()
    client.force_login(user)
    body = client.get(reverse("account_exports")).content.decode()
    assert 'class="empty-state"' in body
