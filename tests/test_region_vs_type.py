"""Тесты «регион против своего типа»: разрыв z-профиля региона и центроида его типа.

Покрывают выборку queries.region_vs_type (разрывы по метрикам, сортировка, типичность)
и эндпоинт /api/regions/<okato>/vs-type/ (200 со структурой, 404 без типа за год).
Данные — мини-витрина во временном DuckDB (регион, кластеры, профиль типа, признаки).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import duckdb
import pytest
from core import duck, queries
from django.test import Client

pytestmark = pytest.mark.django_db


@pytest.fixture
def vs_type_env(tmp_path: Path, settings) -> Iterator[None]:  # type: ignore[no-untyped-def]
    """Мини-витрина: три региона одного типа, профиль типа и z-профиль региона A."""
    path = tmp_path / "vs_type.duckdb"
    con = duckdb.connect(str(path))
    con.execute(
        "CREATE TABLE region_dim(okato VARCHAR, region_name VARCHAR, included_flag BOOLEAN)"
    )
    con.execute(
        "INSERT INTO region_dim VALUES ('01', 'Регион А', TRUE), ('02', 'Регион Б', TRUE), "
        "('03', 'Регион В', TRUE)"
    )
    # Три члена типа 0 с разной удалённостью от центра: А=0.4 (посередине), Б=0.2, В=0.9.
    con.execute(
        "CREATE TABLE clusters(okato VARCHAR, year INTEGER, algo VARCHAR, cluster_id INTEGER, "
        "cluster_label VARCHAR, distance_to_centroid DOUBLE, stability_flag BOOLEAN, k INTEGER)"
    )
    con.execute(
        "INSERT INTO clusters VALUES "
        "('01', 2024, 'kmeans', 0, 'Тип А', 0.4, TRUE, 5), "
        "('02', 2024, 'kmeans', 0, 'Тип А', 0.2, TRUE, 5), "
        "('03', 2024, 'kmeans', 0, 'Тип А', 0.9, TRUE, 5)"
    )
    # metric_id в features_wide — строкой (как в реальной витрине), в metric_dim — числом.
    con.execute(
        "CREATE TABLE features_wide(okato VARCHAR, year INTEGER, metric_id VARCHAR, z_value DOUBLE)"
    )
    con.execute(
        "INSERT INTO features_wide VALUES "
        "('01', 2024, '1404', 1.5), ('01', 2024, '1417', -0.5), ('01', 2024, '1471', 0.1)"
    )
    con.execute("CREATE TABLE metric_dim(metric_id INTEGER, metric_name VARCHAR)")
    con.execute(
        "INSERT INTO metric_dim VALUES (1404, 'Метрика 1404'), (1417, 'Метрика 1417'), "
        "(1471, 'Метрика 1471'), (9999, 'Метрика без значения')"
    )
    con.execute(
        "CREATE TABLE cluster_profile(algo VARCHAR, k INTEGER, year INTEGER, cluster_id INTEGER, "
        "metric_id INTEGER, mean_z DOUBLE)"
    )
    # Центроид типа + метрика 9999, которой нет у региона (должна отсеяться).
    con.execute(
        "INSERT INTO cluster_profile VALUES "
        "('kmeans', 5, 2024, 0, 1404, 0.5), ('kmeans', 5, 2024, 0, 1417, 0.5), "
        "('kmeans', 5, 2024, 0, 1471, 0.0), ('kmeans', 5, 2024, 0, 9999, 2.0)"
    )
    con.close()

    settings.DUCKDB_PATH = str(path)
    duck.reset_connection()
    yield
    duck.reset_connection()


def test_region_vs_type_query(vs_type_env: None) -> None:
    """Разрывы region_z − mean_z, сортировка по |разрыву|, типичность и отсев метрик."""
    data = queries.region_vs_type("01", 2024)
    assert data is not None
    assert data["cluster_id"] == 0
    assert data["cluster_label"] == "Тип А"
    assert data["distance_to_centroid"] == 0.4
    assert data["cluster_size"] == 3
    # А ближе к центру, чем 1 из 2 прочих (Б=0.2) → перцентиль = 1/2.
    assert data["typicality_percentile"] == pytest.approx(0.5)

    metrics = data["metrics"]
    # 9999 нет в профиле региона — отсеяна; остаётся 3 метрики.
    assert {m["metric_id"] for m in metrics} == {1404, 1417, 1471}
    by_id = {m["metric_id"]: m for m in metrics}
    assert by_id[1404]["gap"] == pytest.approx(1.0)  # 1.5 − 0.5
    assert by_id[1417]["gap"] == pytest.approx(-1.0)  # −0.5 − 0.5
    assert by_id[1471]["gap"] == pytest.approx(0.1)  # 0.1 − 0.0
    # Отсортировано по |разрыву| убыванию: крупнейшие (|1.0|) впереди, 1471 (0.1) — последняя.
    assert [abs(m["gap"]) for m in metrics] == sorted(
        (abs(m["gap"]) for m in metrics), reverse=True
    )
    assert metrics[-1]["metric_id"] == 1471


def test_region_vs_type_endpoint_ok(vs_type_env: None) -> None:
    """Эндпоинт возвращает 200 и корректную структуру."""
    resp = Client().get("/api/regions/01/vs-type/?year=2024")
    assert resp.status_code == 200
    body = resp.json()
    assert body["okato"] == "01"
    assert body["cluster_label"] == "Тип А"
    assert body["cluster_size"] == 3
    assert len(body["metrics"]) == 3
    assert body["metrics"][0]["metric_name"].startswith("Метрика")


def test_region_vs_type_endpoint_404_without_type(vs_type_env: None) -> None:
    """Регион без кластера за год → 404."""
    resp = Client().get("/api/regions/99/vs-type/?year=2024")
    assert resp.status_code == 404


def test_region_vs_type_query_none_without_type(vs_type_env: None) -> None:
    """Выборка возвращает None, если у региона нет типа за год."""
    assert queries.region_vs_type("99", 2024) is None
