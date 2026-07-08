"""Тесты сценарного анализа: чистая функция «что если» и эндпойнт на тестовом DuckDB."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import duckdb
import pytest
from core import duck
from core.queries import scenario_from_rows
from rest_framework.test import APIClient

_DOMAINS = ("economy", "income", "demography", "labor", "infrastructure", "health_edu")


def _srow(okato: str, **domains: float) -> dict[str, object]:
    row: dict[str, object] = {"okato": okato}
    for domain in _DOMAINS:
        row[domain] = domains.get(domain, 0.0)
    return row


def _rows() -> list[dict[str, object]]:
    # A лидирует; C выше B. У B слабая «экономика» (0.0) — её и будем подтягивать.
    return [
        _srow(
            "A",
            economy=1.0,
            income=1.0,
            demography=1.0,
            labor=1.0,
            infrastructure=1.0,
            health_edu=1.0,
        ),
        _srow(
            "C",
            economy=0.0,
            income=0.5,
            demography=0.5,
            labor=0.5,
            infrastructure=0.5,
            health_edu=0.5,
        ),
        _srow(
            "B",
            economy=0.0,
            income=0.4,
            demography=0.4,
            labor=0.4,
            infrastructure=0.4,
            health_edu=0.4,
        ),
    ]


def test_scenario_baseline_rank_and_percentiles() -> None:
    """Без изменений: базовое место, перцентили и анализ чувствительности посчитаны."""
    result = scenario_from_rows(_rows(), "B", {})
    assert result is not None
    assert result["of"] == 3
    assert result["baseline_rank"] == 3
    assert result["scenario_rank"] == 3
    assert result["delta"] == 0
    assert set(result["current"]) == set(_DOMAINS)
    # Чувствительность: 6 доменов, по убыванию выигрыша; регион не лидер → верхний домен помогает.
    sens = result["sensitivity"]
    assert len(sens) == len(_DOMAINS)
    assert sens[0]["gain"] >= sens[-1]["gain"]
    assert sens[0]["gain"] > 0


def test_scenario_raising_weak_domain_improves_rank() -> None:
    """Подтягивание слабой «экономики» до 100-го перцентиля поднимает регион с 3-го на 2-е место."""
    result = scenario_from_rows(_rows(), "B", {"economy": 100})
    assert result is not None
    assert result["scenario_rank"] == 2
    assert result["delta"] == 1


def test_scenario_unknown_region_returns_none() -> None:
    assert scenario_from_rows(_rows(), "ZZ", {}) is None


@pytest.fixture
def scenario_duckdb(tmp_path: Path, settings) -> Iterator[Path]:  # type: ignore[no-untyped-def]
    """Временный DuckDB с dev_index; settings.DUCKDB_PATH указывает на него."""
    path = tmp_path / "test.duckdb"
    con = duckdb.connect(str(path))
    con.execute(
        "CREATE TABLE dev_index (okato VARCHAR, year INTEGER, weighting_scheme VARCHAR, "
        "total_score DOUBLE, economy DOUBLE, income DOUBLE, demography DOUBLE, "
        "labor DOUBLE, infrastructure DOUBLE, health_edu DOUBLE)"
    )
    con.execute(
        "INSERT INTO dev_index VALUES "
        "('11', 2020, 'equal', 90.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0), "
        "('22', 2020, 'equal', 50.0, 0.0, 0.5, 0.5, 0.5, 0.5, 0.5), "
        "('33', 2020, 'equal', 30.0, 0.0, 0.4, 0.4, 0.4, 0.4, 0.4)"
    )
    con.close()
    settings.DUCKDB_PATH = str(path)
    duck.reset_connection()
    yield path
    duck.reset_connection()


def test_scenario_endpoint(scenario_duckdb: Path) -> None:
    """Эндпойнт: подтягивание экономики региона поднимает его место."""
    response = APIClient().get(
        "/api/index/scenario/", {"year": 2020, "okato": "33", "p_economy": 100}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["baseline_rank"] == 3
    assert body["scenario_rank"] == 2
    assert body["delta"] == 1
    assert len(body["sensitivity"]) == len(_DOMAINS)


def test_scenario_endpoint_requires_okato(scenario_duckdb: Path) -> None:
    assert APIClient().get("/api/index/scenario/", {"year": 2020}).status_code == 400
