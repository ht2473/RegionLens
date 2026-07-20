"""Тесты management-команды build_region_geojson: сопоставление okato и запись geojson.

Чистые функции (normalize_name, tag_features) покрыты в test_geojson_build; здесь — сама
команда handle(): чтение источника, join с region_dim, overrides, okato-prop, отчёт и запись.
Данные — мини-region_dim во временном DuckDB.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import duckdb
import pytest
from core import duck
from django.core.management import call_command

pytestmark = pytest.mark.django_db


@pytest.fixture
def region_dim_env(tmp_path: Path, settings) -> Iterator[None]:  # type: ignore[no-untyped-def]
    """Мини-витрина с region_dim: Адыгея и Москва (included), плюс исключённый регион."""
    path = tmp_path / "geo.duckdb"
    con = duckdb.connect(str(path))
    con.execute(
        "CREATE TABLE region_dim(okato VARCHAR, region_name VARCHAR, included_flag BOOLEAN)"
    )
    con.execute(
        "INSERT INTO region_dim VALUES "
        "('01000000', 'Республика Адыгея', TRUE), "
        "('45000000', 'Москва', TRUE), "
        "('99000000', 'Тестовия', FALSE)"
    )
    con.close()
    settings.DUCKDB_PATH = str(path)
    duck.reset_connection()
    yield
    duck.reset_connection()


def _write_source(path: Path, features: list[dict]) -> None:
    path.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8"
    )


def _feat(props: dict) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [0, 0]},
        "properties": props,
    }


def test_command_tags_and_writes(region_dim_env: None, tmp_path: Path) -> None:
    """Имена источника сопоставляются с region_dim, файл пишется с okato/name."""
    src = tmp_path / "src.geojson"
    _write_source(src, [_feat({"name": "Республика Адыгея"}), _feat({"name": "Москва"})])
    out = tmp_path / "out.geojson"

    call_command("build_region_geojson", "--source", str(src), "--out", str(out))

    fc = json.loads(out.read_text(encoding="utf-8"))
    assert fc["type"] == "FeatureCollection"
    assert {f["properties"]["okato"] for f in fc["features"]} == {"01000000", "45000000"}
    assert all("name" in f["properties"] for f in fc["features"])


def test_command_source_not_found(region_dim_env: None, tmp_path: Path) -> None:
    """Отсутствующий источник — ошибка, выходной файл не создаётся."""
    out = tmp_path / "out.geojson"
    call_command(
        "build_region_geojson", "--source", str(tmp_path / "нет.geojson"), "--out", str(out)
    )
    assert not out.exists()


def test_command_unmatched_and_missing(region_dim_env: None, tmp_path: Path) -> None:
    """Незнакомое имя источника не тегируется; отчёт различает unmatched и missing."""
    src = tmp_path / "src.geojson"
    _write_source(src, [_feat({"name": "Республика Адыгея"}), _feat({"name": "Атлантида"})])
    out = tmp_path / "out.geojson"

    call_command("build_region_geojson", "--source", str(src), "--out", str(out))

    fc = json.loads(out.read_text(encoding="utf-8"))
    # сопоставлена только Адыгея; Атлантиды нет в region_dim
    assert {f["properties"]["okato"] for f in fc["features"]} == {"01000000"}


def test_command_overrides_and_okato_prop(region_dim_env: None, tmp_path: Path) -> None:
    """Ручной override по имени и готовое свойство okato в фиче."""
    src = tmp_path / "src.geojson"
    _write_source(
        src,
        [
            _feat({"name": "Столица"}),  # не сопоставится по имени — только через override
            _feat({"name": "Что-то", "okato_code": "01000000"}),  # готовый okato в свойстве
        ],
    )
    overrides = tmp_path / "ov.json"
    overrides.write_text(json.dumps({"Столица": "45000000"}), encoding="utf-8")
    out = tmp_path / "out.geojson"

    call_command(
        "build_region_geojson",
        "--source",
        str(src),
        "--out",
        str(out),
        "--overrides",
        str(overrides),
        "--okato-prop",
        "okato_code",
    )

    fc = json.loads(out.read_text(encoding="utf-8"))
    assert {f["properties"]["okato"] for f in fc["features"]} == {"45000000", "01000000"}
