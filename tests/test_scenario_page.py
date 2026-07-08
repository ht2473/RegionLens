"""Тест страницы сценариев: открывается и содержит контейнеры выбора региона и ползунков."""

from __future__ import annotations

import pytest
from django.test import Client

pytestmark = pytest.mark.django_db


def test_scenario_page_renders() -> None:
    response = Client().get("/scenario/")
    assert response.status_code == 200
    body = response.content.decode()
    assert "Сценарии развития региона" in body
    assert "scenario-sliders" in body
    assert "region-select" in body
