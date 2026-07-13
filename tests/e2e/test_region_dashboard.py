"""Дашборд региона: переход из каталога и рендер всех графиков без JS-ошибок.

Самая насыщенная страница приложения (радар, три divergeBars, траектория, SHAP) —
именно на ней проявлялись перекрытия подсказок и панелей. Сценарий проходит путь
пользователя: каталог → первый регион → дождаться отрисовки ключевых графиков.
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.django_db]


def test_region_dashboard_renders_charts(strict_page, live_server) -> None:
    page = strict_page
    page.goto(live_server.url + "/regions/")
    # Каталог регионов рендерится Alpine после fetch — ждём появления ссылок.
    page.wait_for_selector("a.region-chip")

    page.locator("a.region-chip").first.click()

    # Ожидание графиков само подтверждает переход на дашборд: селекторы существуют
    # только там. Явный wait_for_url опущен намеренно — glob-шаблон хрупок из-за
    # query-строки (?year=), которую страница добавляет к адресу.
    page.wait_for_selector("#chart-radar .main-svg", timeout=30_000)
    page.wait_for_selector("#chart-b4 .main-svg, #chart-b4 .chart-note", timeout=30_000)
    page.wait_for_load_state("networkidle")
