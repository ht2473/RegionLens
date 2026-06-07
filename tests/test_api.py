"""Тесты API ядра (Ф6, модуль 1): эндпойнт geo/layer на маленьком тестовом DuckDB.

Без обращения к Postgres/ORM (эндпойнт читает только DuckDB), поэтому маркер
django_db не нужен. settings.DUCKDB_PATH переключается на временный файл, кэш
соединения сбрасывается до и после теста.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import duckdb
import pytest
from core import duck
from rest_framework.test import APIClient


@pytest.fixture
def api_duckdb(tmp_path: Path, settings) -> Iterator[Path]:  # type: ignore[no-untyped-def]
    """Временный DuckDB с clusters и dev_index; settings.DUCKDB_PATH указывает на него."""
    path = tmp_path / "test.duckdb"
    con = duckdb.connect(str(path))
    con.execute(
        "CREATE TABLE clusters (okato VARCHAR, year INTEGER, algo VARCHAR, k INTEGER, "
        "cluster_id INTEGER, cluster_label VARCHAR, silhouette DOUBLE, "
        "stability_flag DOUBLE, distance_to_centroid DOUBLE)"
    )
    con.execute(
        "INSERT INTO clusters VALUES "
        "('45000000', 2020, 'kmeans', 3, 1, '↑доходы', 0.35, 0.96, 0.42), "
        "('46000000', 2020, 'kmeans', 3, 0, '↓доходы', 0.35, 0.96, 1.10), "
        "('47000000', 2019, 'kmeans', 3, 2, '↑жильё', 0.34, NULL, 0.50)"
    )
    con.execute(
        "CREATE TABLE dev_index (okato VARCHAR, year INTEGER, weighting_scheme VARCHAR, "
        "total_score DOUBLE)"
    )
    con.execute(
        "INSERT INTO dev_index VALUES "
        "('45000000', 2020, 'equal', 88.5), ('46000000', 2020, 'equal', 12.3)"
    )
    con.close()

    settings.DUCKDB_PATH = str(path)
    duck.reset_connection()
    yield path
    duck.reset_connection()


def test_geo_layer_cluster(api_duckdb: Path) -> None:
    """measure=cluster → 200 и форма с distance_to_centroid (A1), только нужный год."""
    resp = APIClient().get("/api/geo/layer/", {"year": 2020, "measure": "cluster"})
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 2  # 2019-я строка не должна попасть
    assert set(rows[0]) == {"okato", "cluster_id", "cluster_label", "distance_to_centroid"}
    assert [r["okato"] for r in rows] == ["45000000", "46000000"]  # ORDER BY okato


def test_geo_layer_index(api_duckdb: Path) -> None:
    """measure=index → 200 и форма (okato, total_score)."""
    resp = APIClient().get("/api/geo/layer/", {"year": 2020, "measure": "index"})
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 2
    assert set(rows[0]) == {"okato", "total_score"}


def test_geo_layer_default_measure_is_cluster(api_duckdb: Path) -> None:
    """Без measure используется cluster (слой по умолчанию)."""
    resp = APIClient().get("/api/geo/layer/", {"year": 2020})
    assert resp.status_code == 200
    assert "cluster_id" in resp.json()[0]


def test_geo_layer_missing_year(api_duckdb: Path) -> None:
    """Отсутствие year → 400."""
    assert APIClient().get("/api/geo/layer/").status_code == 400


def test_geo_layer_bad_year(api_duckdb: Path) -> None:
    """Нечисловой year → 400."""
    assert APIClient().get("/api/geo/layer/", {"year": "abc"}).status_code == 400


def test_geo_layer_bad_measure(api_duckdb: Path) -> None:
    """Неизвестный measure → 400."""
    resp = APIClient().get("/api/geo/layer/", {"year": 2020, "measure": "wat"})
    assert resp.status_code == 400
