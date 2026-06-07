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

    # region_dim: 2 включённых субъекта + 1 исключённый вариант-агрегат «с АО».
    con.execute(
        "CREATE TABLE region_dim (okato VARCHAR, oktmo VARCHAR, region_name VARCHAR, "
        "is_aggregate_variant BOOLEAN, federal_district VARCHAR, included_flag BOOLEAN, "
        "geojson_key VARCHAR)"
    )
    con.execute(
        "INSERT INTO region_dim VALUES "
        "('45000000', '45', 'Москва', FALSE, 'Центральный', TRUE, '45000000'), "
        "('46000000', '46', 'Курская область', FALSE, 'Центральный', TRUE, '46000000'), "
        "('11000000', NULL, 'Архангельская область (с АО)', TRUE, 'Северо-Западный', "
        "FALSE, '11000000')"
    )

    # metric_dim: 2 метрики ядра (higher_is_better задан) + 1 «хвост» (excluded, hib NULL).
    con.execute(
        "CREATE TABLE metric_dim (metric_id INTEGER, indicator_code VARCHAR, "
        "subsection VARCHAR, metric_name VARCHAR, unit VARCHAR, section VARCHAR, "
        "domain VARCHAR, value_type VARCHAR, higher_is_better BOOLEAN, coverage DOUBLE)"
    )
    con.execute(
        "INSERT INTO metric_dim VALUES "
        "(1, '0001', 'a', 'Среднедушевые доходы', 'руб', 'Денежные доходы', "
        "'income', 'per_capita', TRUE, 0.99), "
        "(2, '0002', 'b', 'Уровень безработицы', '%', 'Участие в рабочей силе', "
        "'labor', 'share', FALSE, 0.97), "
        "(3, '0003', NULL, 'Индекс цен', '%', 'Уровень и динамика цен', "
        "'excluded', 'index', NULL, 0.80)"
    )

    # fact_region: ряд метрики 1 по региону 45000000 (полный диапазон, есть импутация).
    con.execute(
        "CREATE TABLE fact_region (okato VARCHAR, metric_id INTEGER, year INTEGER, "
        "value DOUBLE, value_harmonized DOUBLE, source VARCHAR, is_imputed BOOLEAN)"
    )
    con.execute(
        "INSERT INTO fact_region VALUES "
        "('45000000', 1, 2019, 50000.0, 50000.0, 's2020', FALSE), "
        "('45000000', 1, 2020, 55000.0, 55000.0, 's2021', FALSE), "
        "('45000000', 1, 2021, 60000.0, NULL, 's2022', TRUE), "
        "('46000000', 1, 2020, 20000.0, 20000.0, 's2021', FALSE)"
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


def test_regions_only_included(api_duckdb: Path) -> None:
    """regions/ → 200, только included_flag=TRUE (вариант-агрегат «с АО» исключён)."""
    resp = APIClient().get("/api/regions/")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 2
    assert set(rows[0]) == {"okato", "region_name", "federal_district"}
    assert "11000000" not in [r["okato"] for r in rows]
    assert [r["region_name"] for r in rows] == ["Курская область", "Москва"]  # ORDER BY имя


def test_metrics_core_only(api_duckdb: Path) -> None:
    """metrics/ → только ядро (higher_is_better задан): метрика 3 (excluded) исключена."""
    resp = APIClient().get("/api/metrics/")
    assert resp.status_code == 200
    rows = resp.json()
    assert {r["metric_id"] for r in rows} == {1, 2}
    assert set(rows[0]) == {
        "metric_id",
        "metric_name",
        "domain",
        "unit",
        "value_type",
        "higher_is_better",
        "coverage",
    }


def test_metrics_domain_filter(api_duckdb: Path) -> None:
    """metrics/?domain=income → только метрики этого домена."""
    resp = APIClient().get("/api/metrics/", {"domain": "income"})
    assert resp.status_code == 200
    rows = resp.json()
    assert [r["metric_id"] for r in rows] == [1]


def test_metric_series_ok(api_duckdb: Path) -> None:
    """series/ → 200, ряд по годам, импутация отражена, форма верна."""
    resp = APIClient().get("/api/metrics/1/series/", {"okato": "45000000"})
    assert resp.status_code == 200
    rows = resp.json()
    assert [r["year"] for r in rows] == [2019, 2020, 2021]  # ORDER BY year
    assert set(rows[0]) == {"year", "value", "value_harmonized", "is_imputed"}
    assert rows[2]["is_imputed"] is True and rows[2]["value_harmonized"] is None


def test_metric_series_year_bounds(api_duckdb: Path) -> None:
    """series/?from=2020 → отсекает ранние годы."""
    resp = APIClient().get("/api/metrics/1/series/", {"okato": "45000000", "from": 2020})
    assert resp.status_code == 200
    assert [r["year"] for r in resp.json()] == [2020, 2021]


def test_metric_series_missing_okato(api_duckdb: Path) -> None:
    """series/ без okato → 400."""
    assert APIClient().get("/api/metrics/1/series/").status_code == 400


def test_metric_series_bad_year(api_duckdb: Path) -> None:
    """series/?from=abc → 400."""
    resp = APIClient().get("/api/metrics/1/series/", {"okato": "45000000", "from": "abc"})
    assert resp.status_code == 400
