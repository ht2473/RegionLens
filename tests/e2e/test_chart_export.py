"""Экспорт графиков Plotly: панель по наведению содержит только экспорт, SVG скачивается.

Регрессии, которые фиксирует тест: (1) страницы создавали графики с displayModeBar:false,
и кнопки экспорта не появлялись вовсе; (2) полный набор из 7 инструментов перекрывал
заголовки карточек. Ожидается ровно две кнопки — PNG (штатная камера) и наш SVG, —
и настоящее скачивание файла .svg, а не только наличие кнопки.
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.django_db]


def test_modebar_is_export_only_and_svg_downloads(strict_page, live_server) -> None:
    page = strict_page
    page.goto(live_server.url + "/compare/")
    # Сравнение автозапускается на первых двух регионах; ждём готовый график Plotly.
    page.wait_for_selector("#chart-compare .main-svg", timeout=30_000)

    page.locator("#chart-compare").hover()
    page.wait_for_selector("#chart-compare .modebar-btn")

    buttons = page.locator("#chart-compare .modebar-btn")
    assert buttons.count() == 2, (
        f"В панели должно быть ровно две кнопки (PNG и SVG), фактически: {buttons.count()}"
    )

    with page.expect_download() as download_info:
        page.locator('#chart-compare .modebar-btn[data-title*="SVG"]').click()
    assert download_info.value.suggested_filename.endswith(".svg")
