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
        "total_score DOUBLE, economy DOUBLE, income DOUBLE, demography DOUBLE, "
        "labor DOUBLE, infrastructure DOUBLE, health_edu DOUBLE)"
    )
    con.execute(
        "INSERT INTO dev_index VALUES "
        # 2019 (предыдущий год — для B4-дельты)
        "('45000000', 2019, 'equal', 80.0, 1.0, 1.5, -0.5, 0.2, 0.8, 0.3), "
        # 2020 (текущий год)
        "('45000000', 2020, 'equal', 88.5, 1.2, 2.0, -0.4, 0.5, 0.9, 0.4), "
        "('46000000', 2020, 'equal', 12.3, -1.0, -0.8, -1.2, -0.3, -0.5, -0.6), "
        "('47000000', 2020, 'equal', 50.0, 0.0, 0.1, -0.2, 0.0, 0.1, 0.0), "
        # другая схема — не должна попадать в equal-выдачу
        "('45000000', 2020, 'pca', 90.0, 1.2, 2.0, -0.4, 0.5, 0.9, 0.4)"
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

    # cluster_shap: вклад метрик в принадлежность 45000000 к типу в 2020.
    con.execute(
        "CREATE TABLE cluster_shap (okato VARCHAR, year INTEGER, metric_id INTEGER, "
        "shap_value DOUBLE)"
    )
    con.execute(
        "INSERT INTO cluster_shap VALUES "
        "('45000000', 2020, 1, 0.90), "
        "('45000000', 2020, 2, -0.30), "
        "('45000000', 2020, 3, 0.05)"
    )

    # transitions: путь региона 45000000 между типами.
    con.execute(
        "CREATE TABLE transitions (okato VARCHAR, year_from INTEGER, year_to INTEGER, "
        "cluster_from INTEGER, cluster_to INTEGER, trajectory_type VARCHAR)"
    )
    con.execute(
        "INSERT INTO transitions VALUES "
        "('45000000', 2019, 2020, 1, 1, 'stable_high'), "
        "('46000000', 2019, 2020, 0, 0, 'stable_low')"
    )

    # cluster_profile: средний z метрик в типе 1 за 2020 (для профиля типа).
    con.execute(
        "CREATE TABLE cluster_profile (algo VARCHAR, k INTEGER, year INTEGER, "
        "cluster_id INTEGER, metric_id INTEGER, mean_z DOUBLE)"
    )
    con.execute(
        "INSERT INTO cluster_profile VALUES "
        "('kmeans', 3, 2020, 1, 1, 1.80), "
        "('kmeans', 3, 2020, 1, 2, -0.40)"
    )

    # region_twins: двойники региона 45000000 за 2020 (C2). 11000000 присутствует в
    # region_dim (вариант-агрегат) — используем его как второй регион-двойник, чтобы
    # проверить порядок по rank и присоединение имени. Строка за 2019 — для проверки
    # фильтра по году.
    con.execute(
        "CREATE TABLE region_twins (okato VARCHAR, year INTEGER, twin_okato VARCHAR, "
        "similarity DOUBLE, rank INTEGER)"
    )
    con.execute(
        "INSERT INTO region_twins VALUES "
        "('45000000', 2020, '46000000', 0.42, 2), "  # вставлен раньше, но rank 2
        "('45000000', 2020, '11000000', 0.88, 1), "  # rank 1 (выше близость)
        "('46000000', 2020, '45000000', 0.42, 1), "
        "('45000000', 2019, '46000000', 0.99, 1)"  # другой год — должен отфильтроваться
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
    assert len(rows) == 3
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


def test_region_dashboard_ok(api_duckdb: Path) -> None:
    """regions/<okato>/ → 200: индекс+B4, кластер, SHAP-топ, ранг — собраны верно."""
    resp = APIClient().get("/api/regions/45000000/", {"year": 2020})
    assert resp.status_code == 200
    d = resp.json()
    assert d["okato"] == "45000000" and d["region_name"] == "Москва"

    idx = d["index"]
    assert idx["total_score"] == 88.5 and idx["total_score_prev"] == 80.0
    assert abs(idx["total_delta"] - 8.5) < 1e-9
    domains = {x["domain"]: x for x in idx["domains"]}
    assert len(domains) == 6
    assert abs(domains["income"]["delta"] - 0.5) < 1e-9  # 2.0 - 1.5

    assert d["cluster"]["cluster_id"] == 1
    assert d["cluster"]["distance_to_centroid"] == 0.42

    # SHAP-топ отсортирован по |value|: метрика 1 (0.90) впереди метрики 3 (0.05)
    assert d["shap_top"][0]["metric_id"] == 1
    assert d["shap_top"][0]["metric_name"] == "Среднедушевые доходы"

    # ранг: 45000000 (88.5) — первый из трёх в 2020
    assert d["rank"] == {"rank": 1, "of": 3}


def test_region_dashboard_no_prev_year(api_duckdb: Path) -> None:
    """Если предыдущего года нет — дельты null, но дашборд отдаётся."""
    resp = APIClient().get("/api/regions/46000000/", {"year": 2020})
    assert resp.status_code == 200
    idx = resp.json()["index"]
    assert idx["total_score_prev"] is None and idx["total_delta"] is None
    assert all(x["delta"] is None for x in idx["domains"])


def test_region_dashboard_not_found(api_duckdb: Path) -> None:
    """Нет записи индекса за год → 404."""
    assert APIClient().get("/api/regions/45000000/", {"year": 1999}).status_code == 404


def test_region_dashboard_missing_year(api_duckdb: Path) -> None:
    """regions/<okato>/ без year → 400."""
    assert APIClient().get("/api/regions/45000000/").status_code == 400


def test_index_ranking(api_duckdb: Path) -> None:
    """index/ → рейтинг по убыванию total_score с рангами; только схема equal."""
    resp = APIClient().get("/api/index/", {"year": 2020})
    assert resp.status_code == 200
    rows = resp.json()
    assert [r["okato"] for r in rows] == ["45000000", "47000000", "46000000"]
    assert [r["rank"] for r in rows] == [1, 2, 3]
    assert set(rows[0]) >= {"rank", "okato", "total_score", "economy", "income"}


def test_index_bad_scheme(api_duckdb: Path) -> None:
    """index/?scheme=bad → 400."""
    assert APIClient().get("/api/index/", {"year": 2020, "scheme": "bad"}).status_code == 400


def test_transitions_by_okato(api_duckdb: Path) -> None:
    """transitions/?okato= → путь региона; форма и тип траектории."""
    resp = APIClient().get("/api/transitions/", {"okato": "45000000"})
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["trajectory_type"] == "stable_high"
    assert set(rows[0]) == {
        "okato",
        "year_from",
        "year_to",
        "cluster_from",
        "cluster_to",
        "trajectory_type",
    }


def test_transitions_all(api_duckdb: Path) -> None:
    """transitions/ без okato → все переходы."""
    resp = APIClient().get("/api/transitions/")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_typology_year(api_duckdb: Path) -> None:
    """typology/?year= → принадлежность регионов к типам за год (только этот год)."""
    resp = APIClient().get("/api/typology/", {"year": 2020})
    assert resp.status_code == 200
    rows = resp.json()
    assert {r["okato"] for r in rows} == {"45000000", "46000000"}
    assert set(rows[0]) == {
        "okato",
        "cluster_id",
        "cluster_label",
        "distance_to_centroid",
        "stability_flag",
    }


def test_typology_explain_ok(api_duckdb: Path) -> None:
    """typology/<okato>/explain/ → SHAP по |вкладу|, с контекстом типа."""
    resp = APIClient().get("/api/typology/45000000/explain/", {"year": 2020})
    assert resp.status_code == 200
    d = resp.json()
    assert d["cluster_id"] == 1
    assert [s["metric_id"] for s in d["shap"]] == [1, 2, 3]  # по убыванию |shap|: 0.9, 0.3, 0.05


def test_typology_explain_not_found(api_duckdb: Path) -> None:
    """Нет региона в типологии за год → 404."""
    resp = APIClient().get("/api/typology/45000000/explain/", {"year": 1999})
    assert resp.status_code == 404


def test_cluster_profile_ok(api_duckdb: Path) -> None:
    """typology/profile/ → профиль типа, метрики по убыванию |mean_z|."""
    resp = APIClient().get("/api/typology/profile/", {"year": 2020, "cluster_id": 1})
    assert resp.status_code == 200
    rows = resp.json()
    assert [r["metric_id"] for r in rows] == [1, 2]  # |1.8| > |0.4|
    assert set(rows[0]) == {"metric_id", "metric_name", "mean_z"}


def test_cluster_profile_missing_cluster_id(api_duckdb: Path) -> None:
    """profile/ без cluster_id → 400."""
    assert APIClient().get("/api/typology/profile/", {"year": 2020}).status_code == 400


def test_compare_ok(api_duckdb: Path) -> None:
    """compare/ с 2 регионами → индекс+тип по каждому, сортировка по убыванию индекса."""
    resp = APIClient().get("/api/compare/", {"year": 2020, "okato": ["45000000", "46000000"]})
    assert resp.status_code == 200
    rows = resp.json()
    assert [r["okato"] for r in rows] == ["45000000", "46000000"]  # 88.5 > 12.3
    assert rows[0]["region_name"] == "Москва" and rows[0]["cluster_id"] == 1
    assert "income" in rows[0]


def test_compare_too_few(api_duckdb: Path) -> None:
    """compare/ с одним регионом → 400 (нужно 2-3)."""
    resp = APIClient().get("/api/compare/", {"year": 2020, "okato": "45000000"})
    assert resp.status_code == 400


def test_exception_handler_unhandled_returns_500() -> None:
    """Единый обработчик: необработанное исключение → 500 с чистым телом."""
    from core.api.exceptions import custom_exception_handler

    resp = custom_exception_handler(RuntimeError("boom"), {"view": None})
    assert resp is not None and resp.status_code == 500
    assert resp.data == {"detail": "внутренняя ошибка сервера"}


def test_openapi_schema_served() -> None:
    """drf-spectacular: схема отдаётся (200)."""
    resp = APIClient().get("/api/schema/")
    assert resp.status_code == 200


def test_swagger_ui_served() -> None:
    """drf-spectacular: Swagger UI отдаётся (200)."""
    resp = APIClient().get("/api/docs/")
    assert resp.status_code == 200


def test_region_twins_ok(api_duckdb: Path) -> None:
    """twins/ → 200; двойники по возрастанию rank, с именем региона; другой год отфильтрован."""
    resp = APIClient().get("/api/regions/45000000/twins/", {"year": 2020})
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 2  # запись за 2019 не попадает
    assert set(rows[0]) == {"rank", "twin_okato", "region_name", "federal_district", "similarity"}
    assert [r["rank"] for r in rows] == [1, 2]  # ORDER BY rank
    assert rows[0]["twin_okato"] == "11000000"  # rank 1 — наибольшая близость
    assert rows[1]["twin_okato"] == "46000000" and rows[1]["region_name"] == "Курская область"


def test_region_twins_empty_for_unknown_year(api_duckdb: Path) -> None:
    """Год без двойников → 200 и пустой список (эндпойнт списочного типа, без 404)."""
    resp = APIClient().get("/api/regions/45000000/twins/", {"year": 2010})
    assert resp.status_code == 200
    assert resp.json() == []


def test_region_twins_missing_year(api_duckdb: Path) -> None:
    """Отсутствие year → 400."""
    assert APIClient().get("/api/regions/45000000/twins/").status_code == 400
