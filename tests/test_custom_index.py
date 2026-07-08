"""Тесты конструктора индекса: чистая функция перевзвешивания и эндпойнт на тестовом DuckDB."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import duckdb
import pytest
from core import duck
from core.queries import custom_ranking_from_rows
from rest_framework.test import APIClient


def _row(okato: str, total: float, **domains: float) -> dict[str, object]:
    base = dict.fromkeys(
        ("economy", "income", "demography", "labor", "infrastructure", "health_edu"), 0.0
    )
    base.update(domains)
    return {"okato": okato, "region_name": okato, "total_score": total, **base}


def test_custom_ranking_reweights_and_ranks() -> None:
    """Вес только на «экономику» поднимает регион с высокой экономикой на первое место."""
    rows = [_row("A", total=10.0, economy=2.0), _row("B", total=90.0, income=2.0)]
    ranking = custom_ranking_from_rows(rows, {"economy": 1.0})
    assert [r["okato"] for r in ranking] == ["A", "B"]
    top = ranking[0]
    assert top["okato"] == "A"
    assert top["rank"] == 1
    # По total_score B был первым (90 > 10), A — вторым; при весе на экономику A поднялся.
    assert top["base_rank"] == 2
    assert top["delta"] == 1


def test_custom_ranking_zero_weights_falls_back_to_equal() -> None:
    """Нулевые веса не ломают расчёт — берутся равные веса."""
    rows = [_row("A", total=10.0, economy=2.0), _row("B", total=90.0, income=2.0)]
    ranking = custom_ranking_from_rows(rows, {})
    assert len(ranking) == 2
    assert {r["rank"] for r in ranking} == {1, 2}


def test_custom_ranking_empty() -> None:
    """Пустой вход — пустой рейтинг."""
    assert custom_ranking_from_rows([], {"economy": 1.0}) == []


@pytest.fixture
def index_duckdb(tmp_path: Path, settings) -> Iterator[Path]:  # type: ignore[no-untyped-def]
    """Временный DuckDB с dev_index и region_dim; settings.DUCKDB_PATH указывает на него."""
    path = tmp_path / "test.duckdb"
    con = duckdb.connect(str(path))
    con.execute(
        "CREATE TABLE dev_index (okato VARCHAR, year INTEGER, weighting_scheme VARCHAR, "
        "total_score DOUBLE, economy DOUBLE, income DOUBLE, demography DOUBLE, "
        "labor DOUBLE, infrastructure DOUBLE, health_edu DOUBLE)"
    )
    con.execute(
        "INSERT INTO dev_index VALUES "
        "('45000000', 2020, 'equal', 90.0, 2.0, 0.0, 0.0, 0.0, 0.0, 0.0), "
        "('46000000', 2020, 'equal', 10.0, 0.0, 2.0, 0.0, 0.0, 0.0, 0.0)"
    )
    con.execute("CREATE TABLE region_dim (okato VARCHAR, region_name VARCHAR)")
    con.execute("INSERT INTO region_dim VALUES ('45000000', 'Москва'), ('46000000', 'Тула')")
    con.close()

    settings.DUCKDB_PATH = str(path)
    duck.reset_connection()
    yield path
    duck.reset_connection()


def test_custom_index_endpoint(index_duckdb: Path) -> None:
    """Эндпойнт возвращает кастомный рейтинг: вес на «доходы» ставит регион с доходами первым."""
    response = APIClient().get("/api/index/custom/", {"year": 2020, "w_income": 1})
    assert response.status_code == 200
    body = response.json()
    assert body[0]["okato"] == "46000000"
    assert body[0]["rank"] == 1
    # По total_score регион с доходами был вторым (10 < 90) — при весе на доходы поднялся.
    assert body[0]["delta"] == 1


def test_custom_index_endpoint_bad_weight(index_duckdb: Path) -> None:
    """Нечисловой вес → 400."""
    response = APIClient().get("/api/index/custom/", {"w_economy": "abc"})
    assert response.status_code == 400
