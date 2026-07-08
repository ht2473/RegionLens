"""Тест страницы конструктора индекса: открывается и содержит контейнер слайдеров весов."""

from __future__ import annotations

import pytest
from django.test import Client

pytestmark = pytest.mark.django_db


def test_index_builder_page_renders() -> None:
    response = Client().get("/index-builder/")
    assert response.status_code == 200
    body = response.content.decode()
    assert "Конструктор индекса" in body
    assert "weight-sliders" in body
