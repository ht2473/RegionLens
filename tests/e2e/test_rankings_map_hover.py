"""Наведение на карту рейтинга: общий DOM-тултип по курсору, без попапа MapLibre.

Регрессия, которую фиксирует тест: карта рейтинга была единственной, где подсказка
рисовалась попапом MapLibre — при обновлении содержимого он на кадр вспыхивал в углу
карты (мерцание и «дубли» информации о регионе). Остальные карты давно используют
DOM-тултип (RL.attachMapHover), который позиционируется у курсора и в углу появиться
не может. Тест проверяет наблюдаемые контракты: при наведении на карту не создаётся
ни одного элемента .maplibregl-popup, а появляется DOM-тултип .rl-chart-tip. Плюс
strict_page роняет тест на любой JS-ошибке (инициализация карт идёт через общую фабрику).
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.django_db]


def test_rankings_map_hover_uses_dom_tip_not_popup(strict_page, live_server) -> None:
    page = strict_page
    page.goto(live_server.url + "/rankings/")
    page.wait_for_load_state("networkidle")

    # Карта загрузилась (канва MapLibre присутствует).
    page.wait_for_selector("#rankings-map canvas")

    box = page.locator("#rankings-map").bounding_box()
    assert box is not None

    # Наводим по сетке точек над центральной областью карты: территория РФ занимает
    # почти весь кадр, поэтому хотя бы одна точка попадёт на субъект и вызовет подсказку.
    saw_tip = False
    for fx in (0.45, 0.55, 0.65, 0.75):
        for fy in (0.45, 0.55, 0.65):
            page.mouse.move(box["x"] + box["width"] * fx, box["y"] + box["height"] * fy)
            page.wait_for_timeout(80)
            # Попап MapLibre не должен создаваться ни в один момент наведения.
            assert page.locator(".maplibregl-popup").count() == 0, (
                "карта рейтинга не должна использовать попап MapLibre (источник мерцания в углу)"
            )
            tip = page.locator(".rl-chart-tip")
            if tip.count() >= 1 and tip.first.is_visible():
                saw_tip = True

    assert saw_tip, "DOM-тултип .rl-chart-tip не появился при наведении на карту рейтинга"
