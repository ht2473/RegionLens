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

    # fact_region: сырые значения (РЕАЛЬНАЯ схема — без harmonized/imputed; они в features_wide).
    con.execute(
        "CREATE TABLE fact_region (okato VARCHAR, metric_id INTEGER, year INTEGER, "
        "value DOUBLE, source VARCHAR)"
    )
    con.execute(
        "INSERT INTO fact_region VALUES "
        "('45000000', 1, 2019, 50000.0, 's2020'), "
        "('45000000', 1, 2020, 55000.0, 's2021'), "
        "('45000000', 1, 2021, 60000.0, 's2022'), "
        "('46000000', 1, 2020, 20000.0, 's2021'), "
        "('45000000', 3, 2020, 105.0, 's2021')"  # не-ядровая метрика: гармонизации не будет
    )

    # features_wide: гармонизованная сетка (только метрики ЯДРА в окне; здесь — метрика 1).
    con.execute(
        "CREATE TABLE features_wide (okato VARCHAR, year INTEGER, metric_id INTEGER, "
        "value_harmonized DOUBLE, z_value DOUBLE, is_imputed BOOLEAN)"
    )
    con.execute(
        "INSERT INTO features_wide VALUES "
        "('45000000', 2019, 1, 50000.0, 0.5, FALSE), "
        "('45000000', 2020, 1, 55000.0, 0.8, FALSE), "
        "('45000000', 2021, 1, NULL, NULL, TRUE), "  # точка импутирована
        "('46000000', 2020, 1, 20000.0, -0.5, FALSE)"
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

    # anomalies (Ф9): пространственный выброс (metric_id NULL), структурный сдвиг (metric 1),
    # кандидат смены методологии A3 (okato NULL, metric 2). Разные kind/год для проверки фильтров.
    con.execute(
        "CREATE TABLE anomalies (okato VARCHAR, metric_id INTEGER, year INTEGER, "
        "score DOUBLE, is_anomaly BOOLEAN, kind VARCHAR)"
    )
    con.execute(
        "INSERT INTO anomalies VALUES "
        "('45000000', NULL, 2020, -0.35, TRUE, 'spatial'), "
        "('46000000', NULL, 2020, 0.12, FALSE, 'spatial'), "
        "('45000000', 1, 2015, 12.5, TRUE, 'structural_break'), "
        "(NULL, 2, 2019, 0.7, TRUE, 'methodology_change')"
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


def _client_with_role(role: str) -> APIClient:
    """APIClient, залогиненный пользователем с заданной ролью (группа создаётся при нужде)."""
    from django.contrib.auth.models import Group, User

    user = User.objects.create_user(username=f"u_{role}", password="x")
    group, _ = Group.objects.get_or_create(name=role)
    user.groups.add(group)
    client = APIClient()
    client.force_login(user)
    return client


def test_anomalies_requires_authentication_anonymous() -> None:
    """Аноним → 403 (эндпойнт аномалий под ролью analyst)."""
    assert APIClient().get("/api/anomalies/").status_code == 403


@pytest.mark.django_db
def test_anomalies_forbidden_for_viewer(api_duckdb: Path) -> None:
    """viewer не имеет доступа к расширенной аналитике → 403."""
    assert _client_with_role("viewer").get("/api/anomalies/").status_code == 403


@pytest.mark.django_db
def test_anomalies_ok_for_analyst(api_duckdb: Path) -> None:
    """analyst → 200; имена подтянуты LEFT JOIN; okato/metric_id NULL там, где положено."""
    resp = _client_with_role("analyst").get("/api/anomalies/")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 4
    by_kind = {r["kind"]: r for r in rows}
    assert by_kind["spatial"]["region_name"] == "Москва"
    assert by_kind["spatial"]["metric_id"] is None and by_kind["spatial"]["metric_name"] is None
    assert by_kind["structural_break"]["metric_name"] == "Среднедушевые доходы"
    meth = by_kind["methodology_change"]
    assert meth["okato"] is None and meth["region_name"] is None
    assert meth["metric_name"] == "Уровень безработицы"


@pytest.mark.django_db
def test_anomalies_filter_by_kind(api_duckdb: Path) -> None:
    """Фильтр kind=spatial → только пространственные строки."""
    rows = _client_with_role("analyst").get("/api/anomalies/", {"kind": "spatial"}).json()
    assert len(rows) == 2 and {r["kind"] for r in rows} == {"spatial"}


@pytest.mark.django_db
def test_anomalies_filter_by_okato(api_duckdb: Path) -> None:
    """Фильтр okato → строки только этого региона (methodology_change с okato NULL не входит)."""
    rows = _client_with_role("analyst").get("/api/anomalies/", {"okato": "45000000"}).json()
    assert {r["kind"] for r in rows} == {"spatial", "structural_break"}
    assert all(r["okato"] == "45000000" for r in rows)


@pytest.mark.django_db
def test_anomalies_invalid_kind_returns_400(api_duckdb: Path) -> None:
    """Неизвестный kind → 400."""
    assert _client_with_role("analyst").get("/api/anomalies/", {"kind": "bogus"}).status_code == 400


@pytest.fixture
def dispersion_duckdb(tmp_path: Path, settings) -> Iterator[Path]:  # type: ignore[no-untyped-def]
    """Временный DuckDB с таблицами dispersion и metric_dim; settings.DUCKDB_PATH → на него."""
    path = tmp_path / "disp.duckdb"
    con = duckdb.connect(str(path))
    con.execute(
        "CREATE TABLE dispersion (metric_id INTEGER, year INTEGER, n_regions INTEGER, "
        "mean DOUBLE, median DOUBLE, std DOUBLE, p10 DOUBLE, p90 DOUBLE, iqr DOUBLE, "
        "value_range DOUBLE, cv DOUBLE, p90_p10_ratio DOUBLE)"
    )
    con.execute(
        "INSERT INTO dispersion VALUES "
        "(1, 2019, 80, 100.0, 95.0, 20.0, 70.0, 140.0, 30.0, 90.0, 0.20, 2.0), "
        "(1, 2020, 80, 110.0, 100.0, 30.0, 70.0, 160.0, 45.0, 110.0, 0.2727, 2.2857), "
        # метрика-индекс: cv и p90_p10_ratio NULL (нет шкалы отношений)
        "(3, 2020, 80, 105.0, 105.0, 5.0, 100.0, 110.0, 6.0, 12.0, NULL, NULL)"
    )
    con.execute("CREATE TABLE metric_dim (metric_id INTEGER, metric_name VARCHAR, domain VARCHAR)")
    con.execute(
        "INSERT INTO metric_dim VALUES "
        "(1, 'Среднедушевые доходы', 'income'), (3, 'Индекс цен', 'excluded')"
    )
    con.close()
    settings.DUCKDB_PATH = str(path)
    duck.reset_connection()
    yield path
    duck.reset_connection()


def test_dispersion_returns_all_rows(dispersion_duckdb: Path) -> None:
    """GET /api/dispersion/ без фильтров отдаёт все строки c подтянутым именем метрики."""
    resp = APIClient().get("/api/dispersion/")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 3
    assert {r["metric_name"] for r in rows} == {"Среднедушевые доходы", "Индекс цен"}
    assert {r["domain"] for r in rows} == {"income", "excluded"}


def test_dispersion_filter_by_metric(dispersion_duckdb: Path) -> None:
    """Фильтр ?metric_id= возвращает только строки этой метрики (ряд по годам)."""
    rows = APIClient().get("/api/dispersion/?metric_id=1").json()
    assert {r["metric_id"] for r in rows} == {1}
    assert sorted(r["year"] for r in rows) == [2019, 2020]


def test_dispersion_filter_by_year(dispersion_duckdb: Path) -> None:
    """Фильтр ?year= возвращает разброс всех метрик за этот год."""
    rows = APIClient().get("/api/dispersion/?year=2020").json()
    assert {r["year"] for r in rows} == {2020}
    assert {r["metric_id"] for r in rows} == {1, 3}


def test_dispersion_year_range(dispersion_duckdb: Path) -> None:
    """Диапазон ?from=&to= ограничивает годы (границы включительно)."""
    rows = APIClient().get("/api/dispersion/?metric_id=1&from=2020&to=2020").json()
    assert [r["year"] for r in rows] == [2020]


def test_dispersion_cv_null_for_non_ratio_metric(dispersion_duckdb: Path) -> None:
    """Для метрики без шкалы отношений cv и p90_p10_ratio приходят как null."""
    rows = APIClient().get("/api/dispersion/?metric_id=3").json()
    assert rows[0]["cv"] is None
    assert rows[0]["p90_p10_ratio"] is None
    # шкало-независимые статистики при этом присутствуют
    assert rows[0]["std"] == 5.0
    assert rows[0]["iqr"] == 6.0


def test_dispersion_bad_numeric_param_returns_400(dispersion_duckdb: Path) -> None:
    """Нечисловой числовой параметр приводит к 400, а не к 500."""
    assert APIClient().get("/api/dispersion/?year=abc").status_code == 400


@pytest.fixture
def rank_stability_duckdb(tmp_path: Path, settings) -> Iterator[Path]:  # type: ignore[no-untyped-def]
    """Временный DuckDB с таблицами rank_stability и region_dim; settings.DUCKDB_PATH → на него."""
    path = tmp_path / "rs.duckdb"
    con = duckdb.connect(str(path))
    con.execute(
        "CREATE TABLE rank_stability (okato VARCHAR, weighting_scheme VARCHAR, n_years INTEGER, "
        "rank_mean DOUBLE, rank_std DOUBLE, rank_min INTEGER, rank_max INTEGER, "
        "rank_range INTEGER, mean_abs_change DOUBLE)"
    )
    con.execute(
        "INSERT INTO rank_stability VALUES "
        "('01', 'equal', 5, 1.0, 0.0, 1, 1, 0, 0.0), "  # стабильный лидер
        "('02', 'equal', 5, 8.0, 1.5, 6, 10, 4, 1.2), "  # дёрганый
        "('01', 'pca', 5, 3.0, 0.7, 2, 4, 2, 0.5)"  # другая схема весов
    )
    con.execute("CREATE TABLE region_dim (okato VARCHAR, region_name VARCHAR)")
    con.execute("INSERT INTO region_dim VALUES ('01', 'Регион А'), ('02', 'Регион Б')")
    con.close()
    settings.DUCKDB_PATH = str(path)
    duck.reset_connection()
    yield path
    duck.reset_connection()


def test_rank_stability_default_scheme(rank_stability_duckdb: Path) -> None:
    """Без параметра отдаётся схема equal, строки отсортированы по rank_std, с именем региона."""
    rows = APIClient().get("/api/rank-stability/").json()
    assert {r["weighting_scheme"] for r in rows} == {"equal"}
    assert [r["okato"] for r in rows] == ["01", "02"]
    assert rows[0]["region_name"] == "Регион А"


def test_rank_stability_scheme_filter(rank_stability_duckdb: Path) -> None:
    """Фильтр ?scheme= возвращает строки только этой схемы весов."""
    rows = APIClient().get("/api/rank-stability/?scheme=pca").json()
    assert {r["weighting_scheme"] for r in rows} == {"pca"}
    assert [r["okato"] for r in rows] == ["01"]


def test_rank_stability_most_stable_first(rank_stability_duckdb: Path) -> None:
    """Самый стабильный регион (минимальный rank_std) идёт первым."""
    rows = APIClient().get("/api/rank-stability/").json()
    assert rows[0]["okato"] == "01"
    assert rows[0]["rank_std"] <= rows[-1]["rank_std"]


def test_rank_stability_invalid_scheme_returns_400(rank_stability_duckdb: Path) -> None:
    """Неизвестная схема весов приводит к 400, а не к пустому/ошибочному ответу."""
    assert APIClient().get("/api/rank-stability/?scheme=bogus").status_code == 400


@pytest.fixture
def correlations_duckdb(tmp_path: Path, settings) -> Iterator[Path]:  # type: ignore[no-untyped-def]
    """Временный DuckDB с таблицами correlations и metric_dim; settings.DUCKDB_PATH → на него."""
    path = tmp_path / "corr.duckdb"
    con = duckdb.connect(str(path))
    con.execute(
        "CREATE TABLE correlations (year INTEGER, metric_a INTEGER, metric_b INTEGER, "
        "method VARCHAR, correlation DOUBLE, n_regions INTEGER)"
    )
    con.execute(
        "INSERT INTO correlations VALUES "
        "(2020, 1, 2, 'spearman', 0.9, 80), "
        "(2020, 1, 3, 'spearman', -0.8, 80), "
        "(2020, 2, 3, 'spearman', 0.2, 80), "
        "(2019, 1, 2, 'spearman', 0.5, 78)"
    )
    con.execute("CREATE TABLE metric_dim (metric_id INTEGER, metric_name VARCHAR)")
    con.execute("INSERT INTO metric_dim VALUES (1, 'Доходы'), (2, 'Зарплата'), (3, 'Безработица')")
    con.close()
    settings.DUCKDB_PATH = str(path)
    duck.reset_connection()
    yield path
    duck.reset_connection()


def test_correlations_requires_authentication_anonymous() -> None:
    """Аноним → 403 (эндпойнт корреляций под ролью analyst)."""
    assert APIClient().get("/api/correlations/").status_code == 403


@pytest.mark.django_db
def test_correlations_forbidden_for_viewer(correlations_duckdb: Path) -> None:
    """viewer не имеет доступа к корреляциям → 403."""
    assert _client_with_role("viewer").get("/api/correlations/").status_code == 403


@pytest.mark.django_db
def test_correlations_default_latest_year_sorted(correlations_duckdb: Path) -> None:
    """analyst, без года → последний год, пары отсортированы по |корреляции|, с именами метрик."""
    rows = _client_with_role("analyst").get("/api/correlations/").json()
    assert {r["year"] for r in rows} == {2020}
    assert [abs(r["correlation"]) for r in rows] == [0.9, 0.8, 0.2]
    assert rows[0]["metric_a_name"] == "Доходы"
    assert rows[0]["metric_b_name"] == "Зарплата"


@pytest.mark.django_db
def test_correlations_filter_by_metric(correlations_duckdb: Path) -> None:
    """Фильтр metric_id возвращает только пары с этой метрикой (в любой позиции)."""
    rows = _client_with_role("analyst").get("/api/correlations/", {"metric_id": 3}).json()
    assert all(r["metric_a"] == 3 or r["metric_b"] == 3 for r in rows)
    assert [abs(r["correlation"]) for r in rows] == [0.8, 0.2]


@pytest.mark.django_db
def test_correlations_year_filter(correlations_duckdb: Path) -> None:
    """Фильтр ?year= ограничивает год."""
    rows = _client_with_role("analyst").get("/api/correlations/", {"year": 2019}).json()
    assert {r["year"] for r in rows} == {2019}
    assert len(rows) == 1


@pytest.mark.django_db
def test_correlations_limit_and_bad_param(correlations_duckdb: Path) -> None:
    """limit ограничивает число пар; нечисловой параметр → 400."""
    client = _client_with_role("analyst")
    rows = client.get("/api/correlations/", {"limit": 1}).json()
    assert len(rows) == 1 and abs(rows[0]["correlation"]) == 0.9
    assert client.get("/api/correlations/", {"year": "abc"}).status_code == 400


@pytest.fixture
def decomposition_duckdb(tmp_path: Path, settings) -> Iterator[Path]:  # type: ignore[no-untyped-def]
    """Временный DuckDB с index_decomposition и region_dim; settings.DUCKDB_PATH → на него."""
    path = tmp_path / "dec.duckdb"
    con = duckdb.connect(str(path))
    con.execute(
        "CREATE TABLE index_decomposition (okato VARCHAR, year INTEGER, weighting_scheme VARCHAR, "
        "domain VARCHAR, delta_total_score DOUBLE, domain_delta DOUBLE, weight DOUBLE, "
        "contribution DOUBLE)"
    )
    con.execute(
        "INSERT INTO index_decomposition VALUES "
        "('01', 2019, 'equal', 'economy', 3.0, 0.9, 0.333, 1.5), "
        "('01', 2019, 'equal', 'income', 3.0, 0.6, 0.333, 1.0), "
        "('01', 2019, 'equal', 'labor', 3.0, 0.3, 0.333, 0.5), "
        "('01', 2020, 'equal', 'economy', 6.0, 1.5, 0.333, 5.0), "
        "('01', 2020, 'equal', 'income', 6.0, 0.6, 0.333, 2.0), "
        "('01', 2020, 'equal', 'labor', 6.0, -0.3, 0.333, -1.0), "
        "('01', 2020, 'pca', 'economy', 4.0, 1.5, 0.5, 3.0), "
        "('01', 2020, 'pca', 'income', 4.0, 0.6, 0.4, 1.0), "
        "('01', 2020, 'pca', 'labor', 4.0, -0.3, 0.1, 0.0)"
    )
    con.execute("CREATE TABLE region_dim (okato VARCHAR, region_name VARCHAR)")
    con.execute("INSERT INTO region_dim VALUES ('01', 'Москва')")
    con.close()
    settings.DUCKDB_PATH = str(path)
    duck.reset_connection()
    yield path
    duck.reset_connection()


def test_decomposition_requires_okato(decomposition_duckdb: Path) -> None:
    """Без обязательного okato → 400."""
    assert APIClient().get("/api/decomposition/").status_code == 400


def test_decomposition_region_sorted_with_name(decomposition_duckdb: Path) -> None:
    """okato + дефолт equal: строки по годам и убыванию |вклада|, с именем региона."""
    rows = APIClient().get("/api/decomposition/", {"okato": "01"}).json()
    assert {r["weighting_scheme"] for r in rows} == {"equal"}
    assert rows[0]["region_name"] == "Москва"
    order = [(r["year"], r["domain"]) for r in rows]
    assert order == [
        (2019, "economy"),
        (2019, "income"),
        (2019, "labor"),
        (2020, "economy"),
        (2020, "income"),
        (2020, "labor"),
    ]


def test_decomposition_year_filter_sums_to_delta(decomposition_duckdb: Path) -> None:
    """Фильтр года → строки этого года; сумма вкладов = delta_total_score."""
    rows = APIClient().get("/api/decomposition/", {"okato": "01", "year": 2020}).json()
    assert {r["year"] for r in rows} == {2020} and len(rows) == 3
    assert sum(r["contribution"] for r in rows) == pytest.approx(rows[0]["delta_total_score"])


def test_decomposition_scheme_filter(decomposition_duckdb: Path) -> None:
    """Фильтр схемы весов возвращает строки только этой схемы."""
    rows = APIClient().get("/api/decomposition/", {"okato": "01", "scheme": "pca"}).json()
    assert {r["weighting_scheme"] for r in rows} == {"pca"}


def test_decomposition_invalid_params_return_400(decomposition_duckdb: Path) -> None:
    """Неизвестная схема и нечисловой год → 400."""
    client = APIClient()
    assert client.get("/api/decomposition/", {"okato": "01", "scheme": "x"}).status_code == 400
    assert client.get("/api/decomposition/", {"okato": "01", "year": "abc"}).status_code == 400


@pytest.fixture
def data_quality_duckdb(tmp_path: Path, settings) -> Iterator[Path]:  # type: ignore[no-untyped-def]
    """Временный DuckDB с таблицами data_quality и metric_dim; settings.DUCKDB_PATH → на него."""
    path = tmp_path / "dq.duckdb"
    con = duckdb.connect(str(path))
    con.execute(
        "CREATE TABLE data_quality (metric_id INTEGER, year INTEGER, n_regions INTEGER, "
        "n_present_raw INTEGER, n_imputed INTEGER, completeness_raw DOUBLE, impute_share DOUBLE)"
    )
    con.execute(
        "INSERT INTO data_quality VALUES "
        "(1, 2019, 80, 80, 0, 1.0, 0.0), "
        "(1, 2020, 80, 76, 4, 0.95, 0.05), "
        # absolute-метрика: сырьё полнее, чем гармонизированное (impute_share>0 при полном сырье)
        "(2, 2020, 80, 80, 8, 1.0, 0.10)"
    )
    con.execute(
        "CREATE TABLE metric_dim (metric_id INTEGER, metric_name VARCHAR, domain VARCHAR, "
        "value_type VARCHAR, coverage DOUBLE)"
    )
    con.execute(
        "INSERT INTO metric_dim VALUES "
        "(1, 'Уровень безработицы', 'labor', 'share', 0.975), "
        "(2, 'ВРП', 'economy', 'absolute', 1.0)"
    )
    con.close()
    settings.DUCKDB_PATH = str(path)
    duck.reset_connection()
    yield path
    duck.reset_connection()


def test_data_quality_returns_all_rows(data_quality_duckdb: Path) -> None:
    """GET /api/data-quality/ без фильтров отдаёт все строки с метаданными метрики."""
    resp = APIClient().get("/api/data-quality/")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 3
    assert {r["metric_name"] for r in rows} == {"Уровень безработицы", "ВРП"}
    assert {r["value_type"] for r in rows} == {"share", "absolute"}


def test_data_quality_filter_by_metric(data_quality_duckdb: Path) -> None:
    """Фильтр ?metric_id= возвращает ряд по годам только этой метрики."""
    rows = APIClient().get("/api/data-quality/?metric_id=1").json()
    assert {r["metric_id"] for r in rows} == {1}
    assert sorted(r["year"] for r in rows) == [2019, 2020]


def test_data_quality_filter_by_year_and_range(data_quality_duckdb: Path) -> None:
    """Фильтры ?year= и диапазон ?from=&to= ограничивают годы (границы включительно)."""
    assert {r["year"] for r in APIClient().get("/api/data-quality/?year=2020").json()} == {2020}
    rows = APIClient().get("/api/data-quality/?metric_id=1&from=2020&to=2020").json()
    assert [r["year"] for r in rows] == [2020]


def test_data_quality_two_completeness_diverge_for_absolute(data_quality_duckdb: Path) -> None:
    """Для absolute-метрики сырьё полное, но доля импутаций > 0 (две полноты расходятся)."""
    rows = APIClient().get("/api/data-quality/?metric_id=2").json()
    assert rows[0]["completeness_raw"] == 1.0
    assert rows[0]["impute_share"] == 0.10
    assert rows[0]["coverage"] == 1.0  # оконное покрытие сырья из metric_dim


def test_data_quality_bad_numeric_param_returns_400(data_quality_duckdb: Path) -> None:
    """Нечисловой числовой параметр приводит к 400, а не к 500."""
    assert APIClient().get("/api/data-quality/?year=abc").status_code == 400


# --- Фаза 2 (зрелость API): корреляция запросов + единый обработчик ошибок ------------


def test_request_id_header_generated() -> None:
    """Без входящего X-Request-ID middleware генерирует свой и возвращает его в ответе."""
    resp = APIClient().get("/api/schema/")
    rid = resp.headers.get("X-Request-ID")
    assert rid and len(rid) >= 8


def test_request_id_header_echoed_when_safe() -> None:
    """Безопасный входящий X-Request-ID отражается в ответе (сквозная корреляция)."""
    resp = APIClient().get("/api/schema/", HTTP_X_REQUEST_ID="abc-123_DEF")
    assert resp.headers.get("X-Request-ID") == "abc-123_DEF"


def test_request_id_rejects_unsafe_incoming() -> None:
    """Небезопасный входящий id (пробелы/управляющие символы) игнорируется — генерируется свой."""
    resp = APIClient().get("/api/schema/", HTTP_X_REQUEST_ID="bad id\r\ninjected")
    rid = resp.headers.get("X-Request-ID")
    assert rid and rid != "bad id\r\ninjected"
    assert "\n" not in rid and " " not in rid


def test_unhandled_error_returns_clean_500(monkeypatch: pytest.MonkeyPatch) -> None:
    """Зарегистрированный обработчик: исключение во вьюхе → чистый 500 + заголовок корреляции."""

    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr("core.queries.geo_layer", boom)
    resp = APIClient().get("/api/geo/layer/", {"year": 2020, "measure": "index"})
    assert resp.status_code == 500
    assert resp.json() == {"detail": "внутренняя ошибка сервера"}
    assert resp.headers.get("X-Request-ID")


# --- Каталог метрик (тиринг core/extended/sparse) ------------------------------------


@pytest.fixture
def metric_catalog_duckdb(tmp_path: Path, settings) -> Iterator[Path]:  # type: ignore[no-untyped-def]
    """Временный DuckDB с таблицей metric_catalog; settings.DUCKDB_PATH → на него."""
    path = tmp_path / "cat.duckdb"
    con = duckdb.connect(str(path))
    con.execute(
        "CREATE TABLE metric_catalog (metric_id INTEGER, indicator_code VARCHAR, "
        "metric_name VARCHAR, domain VARCHAR, value_type VARCHAR, unit VARCHAR, coverage DOUBLE, "
        "year_min INTEGER, year_max INTEGER, n_years INTEGER, n_regions INTEGER, "
        "is_core BOOLEAN, tier VARCHAR)"
    )
    con.execute(
        "INSERT INTO metric_catalog VALUES "
        "(1, 'Y1', 'Индекс развития', 'economy', 'index', 'ед.', "
        "0.99, 2010, 2024, 15, 85, true, 'core'), "
        "(2, 'Y2', 'Ввод жилья', 'infrastructure', 'absolute', 'кв.м', "
        "0.95, 2001, 2024, 24, 85, false, 'extended'), "
        "(3, 'Y3', 'Редкий показатель', 'income', 'share', '%', "
        "0.20, 2015, 2018, 4, 40, false, 'sparse')"
    )
    con.close()
    settings.DUCKDB_PATH = str(path)
    duck.reset_connection()
    yield path
    duck.reset_connection()


def test_metric_catalog_returns_all(metric_catalog_duckdb: Path) -> None:
    """Без фильтров — весь каталог; ядро идёт первым (сортировка по тиру)."""
    rows = APIClient().get("/api/metric-catalog/").json()
    assert len(rows) == 3
    assert rows[0]["tier"] == "core"  # core первым
    assert {r["tier"] for r in rows} == {"core", "extended", "sparse"}


def test_metric_catalog_filter_by_tier(metric_catalog_duckdb: Path) -> None:
    """Фильтр ?tier=extended возвращает только метрики этого тира."""
    rows = APIClient().get("/api/metric-catalog/?tier=extended").json()
    assert [r["metric_name"] for r in rows] == ["Ввод жилья"]


def test_metric_catalog_filter_by_domain_and_search(metric_catalog_duckdb: Path) -> None:
    """Фильтр по домену и текстовый поиск по имени (ILIKE)."""
    assert len(APIClient().get("/api/metric-catalog/?domain=economy").json()) == 1
    rows = APIClient().get("/api/metric-catalog/?search=жил").json()
    assert [r["metric_id"] for r in rows] == [2]


def test_metric_catalog_limit(metric_catalog_duckdb: Path) -> None:
    """limit ограничивает выдачу."""
    assert len(APIClient().get("/api/metric-catalog/?limit=1").json()) == 1


def test_metric_catalog_bad_limit_returns_400(metric_catalog_duckdb: Path) -> None:
    """Нечисловой limit → 400, а не 500."""
    assert APIClient().get("/api/metric-catalog/?limit=abc").status_code == 400


def test_metric_catalog_filter_by_metric_id(metric_catalog_duckdb: Path) -> None:
    """Фильтр ?metric_id=N возвращает одну метрику (для восстановления выбора по ссылке)."""
    rows = APIClient().get("/api/metric-catalog/?metric_id=2").json()
    assert [r["metric_id"] for r in rows] == [2]


# --- Значения метрики по регионам за год (explore: поперечный срез) -------------------


@pytest.fixture
def metric_values_duckdb(tmp_path: Path, settings) -> Iterator[Path]:  # type: ignore[no-untyped-def]
    """Временный DuckDB с region_dim + fact_region; settings.DUCKDB_PATH → на него."""
    path = tmp_path / "mv.duckdb"
    con = duckdb.connect(str(path))
    con.execute(
        "CREATE TABLE region_dim (okato VARCHAR, region_name VARCHAR, included_flag BOOLEAN)"
    )
    con.execute(
        "INSERT INTO region_dim VALUES "
        "('01', 'Регион А', true), ('02', 'Регион Б', true), ('99', 'Исключён', false)"
    )
    con.execute(
        "CREATE TABLE fact_region "
        "(okato VARCHAR, metric_id INTEGER, year INTEGER, value DOUBLE, source VARCHAR)"
    )
    con.execute(
        "INSERT INTO fact_region VALUES "
        "('01', 1, 2020, 30.0, 's'), ('02', 1, 2020, 50.0, 's'), "
        "('99', 1, 2020, 99.0, 's'), "  # исключённый регион — не должен попасть
        "('01', 1, 2020, NULL, 's'), "  # NULL — не должен попасть
        "('01', 1, 2019, 10.0, 's')"  # другой год
    )
    con.close()
    settings.DUCKDB_PATH = str(path)
    duck.reset_connection()
    yield path
    duck.reset_connection()


def test_metric_values_returns_sorted_included(metric_values_duckdb: Path) -> None:
    """Срез за год: только включённые регионы с непустым значением, по убыванию значения."""
    rows = APIClient().get("/api/metric-values/?metric_id=1&year=2020").json()
    assert [r["okato"] for r in rows] == ["02", "01"]  # 50 > 30; 99 (исключён) и NULL отсеяны
    assert rows[0]["region_name"] == "Регион Б" and rows[0]["value"] == 50.0


def test_metric_values_other_year(metric_values_duckdb: Path) -> None:
    """Срез за другой год возвращает данные именно этого года."""
    rows = APIClient().get("/api/metric-values/?metric_id=1&year=2019").json()
    assert [(r["okato"], r["value"]) for r in rows] == [("01", 10.0)]


def test_metric_values_missing_params_returns_400(metric_values_duckdb: Path) -> None:
    """Без обязательных metric_id/year → 400."""
    assert APIClient().get("/api/metric-values/?metric_id=1").status_code == 400
    assert APIClient().get("/api/metric-values/").status_code == 400


def test_metric_values_bad_params_returns_400(metric_values_duckdb: Path) -> None:
    """Нечисловые параметры → 400, а не 500."""
    assert APIClient().get("/api/metric-values/?metric_id=abc&year=2020").status_code == 400


# --- Временной ряд метрики по региону (drill-down: сырое + гармонизация из features_wide) ---


def test_metric_series_core_metric(api_duckdb: Path) -> None:
    """Ряд метрики ядра: сырое value из fact_region + harmonized из features_wide (LEFT JOIN)."""
    rows = APIClient().get("/api/metrics/1/series/?okato=45000000").json()
    assert [r["year"] for r in rows] == [2019, 2020, 2021]
    assert [r["value"] for r in rows] == [50000.0, 55000.0, 60000.0]
    by_year = {r["year"]: r for r in rows}
    assert by_year[2019]["value_harmonized"] == 50000.0
    assert by_year[2021]["value_harmonized"] is None and by_year[2021]["is_imputed"] is True


def test_metric_series_noncore_metric_has_null_harmonized(api_duckdb: Path) -> None:
    """Не-ядровая метрика: сырое value есть, гармонизации нет (NULL) — её нет в features_wide."""
    rows = APIClient().get("/api/metrics/3/series/?okato=45000000").json()
    assert [(r["year"], r["value"]) for r in rows] == [(2020, 105.0)]
    assert rows[0]["value_harmonized"] is None and rows[0]["is_imputed"] is None


def test_metric_series_missing_okato_returns_400(api_duckdb: Path) -> None:
    """Без обязательного okato → 400."""
    assert APIClient().get("/api/metrics/1/series/").status_code == 400
