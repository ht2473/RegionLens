"""Стабильность шапки: высота не зависит от состояния входа и страницы.

Регрессия, которую фиксирует тест: `<button>` (дропдауны, аккаунт) и `<a>` (Войти/
Регистрация) получали разный line-height от браузера, из-за чего шапка «прыгала»
на 4px между состояниями входа. Измеряется фактическая геометрия .header-row.
"""

from __future__ import annotations

import pytest

from tests.e2e.conftest import login

pytestmark = [pytest.mark.e2e, pytest.mark.django_db]

# Допуск в 1px покрывает субпиксельное округление при измерении bounding box.
TOLERANCE_PX = 1.0


def header_height(page, url: str) -> float:
    page.goto(url)
    box = page.locator(".header-row").bounding_box()
    assert box is not None, "Шапка не найдена на " + url
    return box["height"]


def test_header_height_identical_for_anon_and_authenticated(
    strict_page, live_server, user_credentials
) -> None:
    page = strict_page
    h_anon_home = header_height(page, live_server.url + "/")
    h_anon_rankings = header_height(page, live_server.url + "/rankings/")

    login(page, live_server.url, user_credentials)
    h_auth_home = header_height(page, live_server.url + "/")
    h_auth_rankings = header_height(page, live_server.url + "/rankings/")

    heights = [h_anon_home, h_anon_rankings, h_auth_home, h_auth_rankings]
    assert max(heights) - min(heights) <= TOLERANCE_PX, (
        f"Высота шапки меняется между состояниями/страницами: {heights}"
    )
