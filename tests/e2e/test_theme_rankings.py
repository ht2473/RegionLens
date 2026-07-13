"""Переключение темы на странице рейтинга: токены обновляются и переживают перезагрузку.

Регрессия, которую фиксирует тест: карта рейтинга была единственной без подписки на
смену темы — фон «застывал». Сам paint MapLibre из теста не читается (WebGL), поэтому
проверяются наблюдаемые контракты: атрибут data-theme, CSS-переменная --map-bg (её
значение карты берут при перекраске) и наличие канвы карты после переключения.
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.django_db]


def css_var(page, name: str) -> str:
    return page.evaluate(
        "n => getComputedStyle(document.documentElement).getPropertyValue(n).trim()", name
    )


def test_theme_toggle_updates_tokens_and_persists(strict_page, live_server) -> None:
    page = strict_page
    page.goto(live_server.url + "/rankings/")
    page.wait_for_load_state("networkidle")

    theme_before = page.get_attribute("html", "data-theme")
    map_bg_before = css_var(page, "--map-bg")

    page.locator(".theme-toggle").click()

    theme_after = page.get_attribute("html", "data-theme")
    map_bg_after = css_var(page, "--map-bg")
    assert theme_after != theme_before, "data-theme не переключился"
    assert map_bg_after != map_bg_before, "--map-bg не изменился при смене темы"

    # Канва карты присутствует и после переключения (перекраска не уронила MapLibre).
    assert page.locator("#rankings-map canvas").count() >= 1

    # Выбор темы хранится в localStorage — перезагрузка не сбрасывает его.
    page.reload()
    assert page.get_attribute("html", "data-theme") == theme_after
