"""Комбобокс «Неравенства»: подпись полного названия строго при реальном переполнении.

Регрессия, которую фиксирует тест: подпись показывалась по эвристике «>40 символов»
и дублировала название, даже когда широкое поле вмещало его целиком. Инвариант ниже
проверяется на самом длинном и самом коротком названиях из реального каталога метрик.
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.django_db]

# Инвариант: подпись видима тогда и только тогда, когда текст физически не помещается.
INVARIANT_JS = """() => {
  const input = document.querySelector(".combo-input");
  const caption = document.querySelector(".combo-selected");
  const overflowing = input.scrollWidth > input.clientWidth + 1;
  return { overflowing, captionHidden: caption.hidden,
           value: input.value, caption: caption.textContent };
}"""

SELECT_BY_LENGTH_JS = """(longest) => {
  const s = document.getElementById("metric-select");
  let idx = 0, best = longest ? -1 : Infinity;
  [...s.options].forEach((o, k) => {
    const len = o.textContent.trim().length;
    if ((longest && len > best) || (!longest && len < best)) { best = len; idx = k; }
  });
  s.selectedIndex = idx;
  s.dispatchEvent(new Event("change"));
}"""


def assert_invariant(page) -> None:
    state = page.evaluate(INVARIANT_JS)
    assert state["captionHidden"] == (not state["overflowing"]), (
        "Подпись не соответствует переполнению: " + repr(state)
    )
    if not state["captionHidden"]:
        # Показанная подпись обязана дублировать именно выбранное значение целиком.
        assert state["caption"] == state["value"]


def test_caption_matches_real_overflow(strict_page, live_server) -> None:
    page = strict_page
    page.goto(live_server.url + "/dispersion/")
    # Дождаться каталога метрик (fetch) и улучшения селекта до комбобокса.
    page.wait_for_selector(".combo-input")
    page.wait_for_function("document.querySelectorAll('#metric-select option').length > 3")

    assert_invariant(page)  # выбранная по умолчанию метрика

    page.evaluate(SELECT_BY_LENGTH_JS, True)  # самое длинное название
    assert_invariant(page)

    page.evaluate(SELECT_BY_LENGTH_JS, False)  # самое короткое название
    assert_invariant(page)
