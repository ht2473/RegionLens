"""Онбординг на главной: закрывается крестиком и не возвращается после перезагрузки.

Регрессия, которую фиксирует тест: правило .onboarding{display:flex} перекрывало
атрибут [hidden], и баннер не скрывался ни по крестику, ни для уже отклонивших его.
Каждый тест получает свежий контекст браузера (чистый localStorage), поэтому баннер
гарантированно виден в начале сценария.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import expect

pytestmark = [pytest.mark.e2e, pytest.mark.django_db]


def test_onboarding_dismiss_persists(strict_page, live_server) -> None:
    page = strict_page
    page.goto(live_server.url + "/")
    banner = page.locator("#rl-onboarding")
    expect(banner).to_be_visible()

    page.locator("#rl-onboarding-close").click()
    expect(banner).to_be_hidden()

    # Отклонение сохраняется в localStorage — после перезагрузки баннер не возвращается.
    page.reload()
    expect(banner).to_be_hidden()
