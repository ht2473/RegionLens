"""Тесты сборки GeoJSON с okato: нормализация имён и проставление ключа.

Чистые функции — без Django/DuckDB.
"""

from __future__ import annotations

from typing import Any

from core.management.commands.build_region_geojson import normalize_name, tag_features


def test_normalize_strips_type_words_and_case() -> None:
    assert normalize_name("Республика Адыгея") == "адыгея"
    assert normalize_name("г. Москва") == "москва"
    assert normalize_name("Ханты-Мансийский автономный округ") == "ханты-мансийский"
    assert normalize_name("Орловская область") == "орловская"


def test_normalize_handles_yo_and_parentheses() -> None:
    assert normalize_name("Орёл") == "орел"
    assert normalize_name("Архангельская область (с автономным округом)") == "архангельская"


def _feat(props: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": []},
        "properties": props,
    }


def test_tag_by_name_match() -> None:
    index = {"адыгея": "01000000", "москва": "45000000"}
    feats = [_feat({"name": "Республика Адыгея"}), _feat({"name": "Москва"})]
    tagged, unmatched = tag_features(feats, index)
    assert unmatched == []
    assert [f["properties"]["okato"] for f in tagged] == ["01000000", "45000000"]
    assert tagged[0]["properties"]["name"] == "Республика Адыгея"
    assert tagged[0]["geometry"]["type"] == "Polygon"


def test_tag_by_okato_prop_directly() -> None:
    feats = [_feat({"name": "Что-угодно", "OKATO": "77000000"})]
    tagged, unmatched = tag_features(feats, {}, okato_prop="OKATO")
    assert unmatched == []
    assert tagged[0]["properties"]["okato"] == "77000000"


def test_tag_overrides_take_priority() -> None:
    index = {"адыгея": "01000000"}
    feats = [_feat({"name": "Кабардино-Балкария"})]
    tagged, unmatched = tag_features(feats, index, overrides={"Кабардино-Балкария": "83000000"})
    assert unmatched == []
    assert tagged[0]["properties"]["okato"] == "83000000"


def test_tag_reports_unmatched() -> None:
    feats = [_feat({"name": "Неизвестная земля"})]
    tagged, unmatched = tag_features(feats, {"адыгея": "01000000"})
    assert tagged == []
    assert unmatched == ["Неизвестная земля"]
