"""Тесты пространственной автокорреляции: соседство, Moran's I/LISA и эндпоинты.

Покрывают build_adjacency на реальном geojson (смежность субъектов), compute_moran (глобальный
индекс и LISA — гладкая величина даёт значимую положительную автокорреляцию, шум — нет; изоляты
помечены ns), и API /api/spatial/moran/ + /api/spatial/lisa/ на мини-витрине во временном DuckDB.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import duckdb
import numpy as np
import polars as pl
import pytest
from core import duck
from django.test import Client

from pipeline.spatial import build_adjacency, compute_moran

pytestmark = pytest.mark.django_db


def test_build_adjacency_real_geojson() -> None:
    """Соседство субъектов: 85 регионов, симметрично, ровно 2 изолята (остров + эксклав)."""
    nb = build_adjacency()
    assert len(nb) == 85
    # симметрия: если A сосед B, то B сосед A
    assert all(a in nb[b] for a, neigh in nb.items() for b in neigh)
    # эксклав (Калининград) и остров (Сахалин) не имеют сухопутных соседей
    isolates = [ok for ok, neigh in nb.items() if not neigh]
    assert len(isolates) == 2
    # средняя степень в разумном диапазоне для смежности регионов
    avg = sum(len(v) for v in nb.values()) / len(nb)
    assert 3.0 < avg < 6.0


def test_compute_moran_detects_spatial_structure() -> None:
    """Гладкая по пространству величина — значимая положительная автокорреляция; шум — нет."""
    nb = build_adjacency()
    rng = np.random.default_rng(0)
    rows = []
    for ok in nb:
        rows.append(
            {"okato": ok, "year": 1, "weighting_scheme": "equal", "total_score": float(len(nb[ok]))}
        )
        rows.append(
            {
                "okato": ok,
                "year": 2,
                "weighting_scheme": "equal",
                "total_score": float(rng.normal()),
            }
        )
    g, local = compute_moran(pl.DataFrame(rows), nb)

    by_year = {r["year"]: r for r in g.to_dicts()}
    assert by_year[1]["morans_i"] > 0.1  # гладкая величина — положительная автокорреляция
    assert by_year[1]["p_value"] < 0.05  # и значимая
    assert abs(by_year[2]["morans_i"]) < by_year[1]["morans_i"]  # шум — заметно слабее
    # n_regions = 85 минус изоляты
    assert by_year[1]["n_regions"] == 83

    # LISA: строка на каждый регион в каждый год; изоляты — ns без значения
    assert local.height == 2 * len(nb)
    isolate_rows = local.filter(pl.col("n_neighbors") == 0)
    assert (isolate_rows["quadrant"] == "ns").all()
    assert isolate_rows["p_value"].is_null().all()
    # квадранты — из допустимого набора
    assert set(local["quadrant"].unique()).issubset({"HH", "LL", "HL", "LH", "ns"})


@pytest.fixture
def moran_env(tmp_path: Path, settings) -> Iterator[None]:  # type: ignore[no-untyped-def]
    """Мини-витрина с moran_global/moran_local и region_dim за (2024, equal)."""
    path = tmp_path / "moran.duckdb"
    con = duckdb.connect(str(path))
    con.execute(
        "CREATE TABLE region_dim(okato VARCHAR, region_name VARCHAR, included_flag BOOLEAN)"
    )
    con.execute("INSERT INTO region_dim VALUES ('01','Регион А',TRUE), ('02','Регион Б',TRUE)")
    con.execute(
        "CREATE TABLE moran_global(weighting_scheme VARCHAR, year INTEGER, morans_i DOUBLE, "
        "expected_i DOUBLE, z_score DOUBLE, p_value DOUBLE, n_regions INTEGER)"
    )
    con.execute("INSERT INTO moran_global VALUES ('equal', 2024, 0.42, -0.012, 3.1, 0.004, 83)")
    con.execute(
        "CREATE TABLE moran_local(weighting_scheme VARCHAR, year INTEGER, okato VARCHAR, "
        "local_i DOUBLE, quadrant VARCHAR, p_value DOUBLE, n_neighbors INTEGER)"
    )
    con.execute(
        "INSERT INTO moran_local VALUES "
        "('equal',2024,'01',0.8,'HH',0.01,4), ('equal',2024,'02',NULL,'ns',NULL,0)"
    )
    con.close()
    settings.DUCKDB_PATH = str(path)
    duck.reset_connection()
    yield
    duck.reset_connection()


def test_moran_global_endpoint(moran_env: None) -> None:
    resp = Client().get("/api/spatial/moran/?year=2024&scheme=equal")
    assert resp.status_code == 200
    body = resp.json()
    assert body["morans_i"] == pytest.approx(0.42)
    assert body["n_regions"] == 83


def test_moran_global_404_when_not_computed(moran_env: None) -> None:
    assert Client().get("/api/spatial/moran/?year=2099&scheme=equal").status_code == 404


def test_moran_global_400_bad_scheme(moran_env: None) -> None:
    assert Client().get("/api/spatial/moran/?year=2024&scheme=bogus").status_code == 400


def test_moran_local_endpoint(moran_env: None) -> None:
    resp = Client().get("/api/spatial/lisa/?year=2024&scheme=equal")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 2
    by_okato = {r["okato"]: r for r in rows}
    assert by_okato["01"]["quadrant"] == "HH"
    assert by_okato["01"]["name"] == "Регион А"
    assert by_okato["02"]["quadrant"] == "ns"
    assert by_okato["02"]["local_i"] is None
