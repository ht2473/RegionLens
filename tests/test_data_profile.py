"""Тесты сводки по данным/методологии (обогащение страниц «Данные»/«Методология»).

Сводка `queries.data_profile()` выводится запросом к контрактным таблицам DuckDB (без
отдельной materialized-таблицы и без пересчёта на лету). Проверяем агрегаты на маленьком
тестовом DuckDB, рендер чисел на страницах и мягкую деградацию, когда хранилище недоступно.
Обращения только к DuckDB (не к ORM/Postgres), поэтому маркер django_db не нужен; кэш
соединения сбрасывается до и после теста.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import duckdb
import pytest
from core import duck, queries
from django.test import Client


@pytest.fixture
def profile_duckdb(tmp_path: Path, settings) -> Iterator[Path]:  # type: ignore[no-untyped-def]
    """Временный DuckDB со всеми таблицами, нужными data_profile; путь — в settings."""
    path = tmp_path / "profile.duckdb"
    con = duckdb.connect(str(path))

    # region_dim: 3 включённых субъекта (2 ЦФО + 1 СЗФО) + 1 исключённый агрегат «с АО».
    con.execute(
        "CREATE TABLE region_dim (okato VARCHAR, oktmo VARCHAR, region_name VARCHAR, "
        "is_aggregate_variant BOOLEAN, federal_district VARCHAR, included_flag BOOLEAN, "
        "geojson_key VARCHAR)"
    )
    con.execute(
        "INSERT INTO region_dim VALUES "
        "('45000000','45','Москва',FALSE,'Центральный',TRUE,'45000000'), "
        "('46000000','46','Курская область',FALSE,'Центральный',TRUE,'46000000'), "
        "('78000000','78','Санкт-Петербург',FALSE,'Северо-Западный',TRUE,'78000000'), "
        "('11000000',NULL,'Архангельская область (с АО)',TRUE,'Северо-Западный',FALSE,'11000000')"
    )

    # fact_region: ряды по двум изданиям, годы 2001..2024 (диапазон отображения).
    con.execute(
        "CREATE TABLE fact_region (okato VARCHAR, metric_id INTEGER, year INTEGER, "
        "value DOUBLE, value_harmonized DOUBLE, source VARCHAR, is_imputed BOOLEAN)"
    )
    con.execute(
        "INSERT INTO fact_region VALUES "
        "('45000000',1,2001,1.0,1.0,'s2010',FALSE), "
        "('45000000',1,2010,2.0,2.0,'s2010',FALSE), "
        "('45000000',1,2024,3.0,3.0,'s2024',FALSE), "
        "('46000000',1,2024,4.0,4.0,'s2024',FALSE), "
        "('78000000',2,2024,5.0,5.0,'s2024',FALSE), "
        "('46000000',2,2010,6.0,6.0,'s2010',FALSE)"
    )

    # metric_dim: 3 ядра (higher_is_better задан) + 2 «хвоста» (hib NULL). Покрытие разное
    # — для проверки воронки. value_type у ядра: per_capita×2, share×1.
    con.execute(
        "CREATE TABLE metric_dim (metric_id INTEGER, indicator_code VARCHAR, "
        "subsection VARCHAR, metric_name VARCHAR, unit VARCHAR, section VARCHAR, "
        "domain VARCHAR, value_type VARCHAR, higher_is_better BOOLEAN, coverage DOUBLE)"
    )
    con.execute(
        "INSERT INTO metric_dim VALUES "
        "(1,'0001','a','Доходы','руб','Денежные доходы','income','per_capita',TRUE,0.99), "
        "(2,'0002','b','Безработица','%','Рынок труда','labor','share',FALSE,0.97), "
        "(3,'0003','c','Расходы','руб','Денежные доходы','income','per_capita',TRUE,0.92), "
        "(4,'0004',NULL,'Индекс цен','%','Цены','excluded','index',NULL,0.40), "
        "(5,'0005',NULL,'Прочее','ед','Прочее','excluded','absolute',NULL,0.85)"
    )

    # features_wide: 10 ячеек, 2 импутированы (доля 20%); окно 2010..2024; 3 региона, 3 метрики.
    con.execute(
        "CREATE TABLE features_wide (okato VARCHAR, year INTEGER, metric_id INTEGER, "
        "value_harmonized DOUBLE, z_value DOUBLE, is_imputed BOOLEAN)"
    )
    con.execute(
        "INSERT INTO features_wide VALUES "
        "('45000000',2010,1,2.0,0.0,FALSE), ('45000000',2024,1,3.0,0.1,FALSE), "
        "('46000000',2010,1,2.5,0.0,FALSE), ('46000000',2024,1,3.5,0.2,TRUE), "
        "('78000000',2010,1,2.2,0.0,FALSE), ('78000000',2024,1,3.2,0.1,FALSE), "
        "('45000000',2010,2,1.0,0.0,FALSE), ('45000000',2024,2,1.2,0.3,TRUE), "
        "('46000000',2010,3,4.0,0.0,FALSE), ('78000000',2024,3,4.2,0.1,FALSE)"
    )

    # clusters: kmeans k=3 за два года (+ строка ward, которую фильтр должен отбросить).
    con.execute(
        "CREATE TABLE clusters (okato VARCHAR, year INTEGER, algo VARCHAR, k INTEGER, "
        "cluster_id INTEGER, cluster_label VARCHAR, silhouette DOUBLE, "
        "stability_flag DOUBLE, distance_to_centroid DOUBLE)"
    )
    con.execute(
        "INSERT INTO clusters VALUES "
        "('45000000',2010,'kmeans',3,1,'lbl',0.30,NULL,0.5), "
        "('46000000',2010,'kmeans',3,0,'lbl',0.30,NULL,1.0), "
        "('45000000',2024,'kmeans',3,1,'lbl',0.40,0.90,0.5), "
        "('46000000',2024,'kmeans',3,0,'lbl',0.40,0.90,1.0), "
        "('45000000',2024,'ward',3,1,'lbl',0.20,0.50,0.5)"
    )

    # dev_index: три схемы весов.
    con.execute(
        "CREATE TABLE dev_index (okato VARCHAR, year INTEGER, weighting_scheme VARCHAR, "
        "total_score DOUBLE, economy DOUBLE, income DOUBLE, demography DOUBLE, "
        "labor DOUBLE, infrastructure DOUBLE, health_edu DOUBLE)"
    )
    con.execute(
        "INSERT INTO dev_index VALUES "
        "('45000000',2024,'equal',80.0,1,1,1,1,1,1), "
        "('45000000',2024,'pca',82.0,1,1,1,1,1,1), "
        "('45000000',2024,'expert',81.0,1,1,1,1,1,1)"
    )
    con.close()

    settings.DUCKDB_PATH = str(path)
    duck.reset_connection()
    yield path
    duck.reset_connection()


def test_profile_regions_and_fact(profile_duckdb: Path) -> None:
    """Охват: включённые субъекты, исключённые агрегаты, ФО, источники, диапазон лет."""
    p = queries.data_profile()
    assert p is not None
    assert p["regions"] == {"included": 3, "aggregates": 1, "districts": 2}
    assert p["fact"]["sources"] == 2
    assert p["fact"]["year_min"] == 2001
    assert p["fact"]["year_max"] == 2024


def test_profile_metrics_and_core_by_domain(profile_duckdb: Path) -> None:
    """Метрик всего/в ядре и состав ядра по доменам (с подписями, по убыванию)."""
    p = queries.data_profile()
    assert p is not None
    assert p["metrics"] == {"total": 5, "core": 3}
    assert p["core_by_domain"] == [
        {"domain": "income", "n": 2, "label": "Доходы"},
        {"domain": "labor", "n": 1, "label": "Рынок труда"},
    ]


def test_profile_value_types(profile_duckdb: Path) -> None:
    """Формы значений в ядре: per_capita преобладает, с человекочитаемой подписью."""
    p = queries.data_profile()
    assert p is not None
    assert p["value_types"][0] == {
        "value_type": "per_capita",
        "n": 2,
        "label": "на душу населения",
    }
    assert {v["value_type"] for v in p["value_types"]} == {"per_capita", "share"}


def test_profile_coverage_funnel(profile_duckdb: Path) -> None:
    """Воронка покрытия по ВСЕМ метрикам (ge95<ge90<ge80, m4 с 0.40 вне ge50)."""
    p = queries.data_profile()
    assert p is not None
    assert p["coverage"] == {"ge95": 2, "ge90": 3, "ge80": 4, "ge50": 4}


def test_profile_features_imputation(profile_duckdb: Path) -> None:
    """Признаки: ячейки/импутации/доля и границы окна расчёта."""
    p = queries.data_profile()
    assert p is not None
    fw = p["features"]
    assert fw["cells"] == 10
    assert fw["imputed"] == 2
    assert fw["impute_pct"] == 20.0
    assert fw["regions"] == 3
    assert fw["metrics"] == 3
    assert fw["window_start"] == 2010
    assert fw["window_end"] == 2024


def test_profile_clustering_kmeans_only(profile_duckdb: Path) -> None:
    """Качество типологии считается по kmeans (строка ward отброшена)."""
    p = queries.data_profile()
    assert p is not None
    assert len(p["clustering"]) == 1
    row = p["clustering"][0]
    assert row["k"] == 3
    assert row["silhouette"] == pytest.approx(0.35)
    assert row["stability_pct"] == 90.0
    assert row["years"] == 2


def test_profile_index_schemes(profile_duckdb: Path) -> None:
    """Индекс: число различных схем весов."""
    p = queries.data_profile()
    assert p is not None
    assert p["index"]["schemes"] == 3
    assert p["index"]["rows"] == 3


def test_data_page_renders_numbers(client: Client, profile_duckdb: Path) -> None:
    """Страница «Данные»: KPI-блок и таблица воронки отбора отрисованы при наличии данных."""
    html = client.get("/data/").content.decode()
    assert "kpi-row" in html
    assert "Ступень отбора" in html
    assert "Курируемое ядро" in html


def test_methodology_page_renders_numbers(client: Client, profile_duckdb: Path) -> None:
    """Страница «Методология»: KPI-блок, состав ядра по доменам и подпись домена."""
    html = client.get("/methodology/").content.decode()
    assert "kpi-row" in html
    assert "Состав ядра по доменам" in html
    assert "Доходы" in html


def test_pages_degrade_without_store(client: Client, tmp_path: Path, settings) -> None:  # type: ignore[no-untyped-def]
    """Нет собранного DuckDB → data_profile() = None, страницы живы и без блока чисел."""
    settings.DUCKDB_PATH = str(tmp_path / "absent.duckdb")
    duck.reset_connection()
    try:
        assert queries.data_profile() is None
        for url in ("/data/", "/methodology/"):
            resp = client.get(url)
            assert resp.status_code == 200
            assert "kpi-row" not in resp.content.decode()
    finally:
        duck.reset_connection()
