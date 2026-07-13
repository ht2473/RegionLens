"""Смоук: ключевые публичные страницы открываются без JS-ошибок.

Один параметризованный тест — широкая «сеть» на целый класс дефектов: битые импорты,
отсутствующие CDN-теги (как пропавший Plotly на сценариях), ошибки инициализации карт
и графиков. Ассерты выполняет фикстура strict_page на выходе из теста.
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.django_db]

# Страницы с разными классами виджетов: карты MapLibre, графики Plotly, Alpine-каталоги,
# комбобоксы. Кабинет не включён — он проверяется сценарием со входом отдельно.
PAGES = [
    "/",
    "/map/",
    "/rankings/",
    "/regions/",
    "/compare/",
    "/dispersion/",
    "/correlations/",
    "/anomalies/",
    "/scenario/",
    "/index-builder/",
    "/methodology/",
]


@pytest.mark.parametrize("path", PAGES)
def test_page_loads_without_js_errors(strict_page, live_server, path: str) -> None:
    strict_page.goto(live_server.url + path)
    # networkidle дожидается CDN-скриптов (Plotly, MapLibre) и первых fetch к API,
    # чтобы ошибки инициализации успели проявиться до финальной проверки фикстуры.
    strict_page.wait_for_load_state("networkidle")
