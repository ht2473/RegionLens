"""Горячие клавиши поиска: раскладко-независимый Ctrl+K, «/», закрытие по Escape.

Регрессия, которую фиксирует тест: проверка по символу (e.key === "k") не срабатывала
в кириллической раскладке, где физическая клавиша K даёт «л». Исправление опирается
на e.code === "KeyK"; сценарий эмулирует именно кириллическое событие.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import expect

pytestmark = [pytest.mark.e2e, pytest.mark.django_db]


def test_ctrl_k_opens_search_in_cyrillic_layout(strict_page, live_server) -> None:
    page = strict_page
    page.goto(live_server.url + "/")
    # Синтетическое событие воспроизводит русскую раскладку точно: key="л" при code="KeyK".
    # page.keyboard.press("Control+k") такого не умеет — он всегда шлёт латинский key.
    page.evaluate(
        """document.dispatchEvent(new KeyboardEvent("keydown",
             { key: "л", code: "KeyK", ctrlKey: true, bubbles: true }))"""
    )
    expect(page.locator("#site-search")).to_be_visible()

    page.keyboard.press("Escape")
    expect(page.locator("#site-search")).to_be_hidden()


def test_slash_opens_search_when_not_typing(strict_page, live_server) -> None:
    page = strict_page
    page.goto(live_server.url + "/")
    page.keyboard.press("/")
    expect(page.locator("#site-search")).to_be_visible()
