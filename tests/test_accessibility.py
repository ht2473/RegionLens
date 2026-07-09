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
