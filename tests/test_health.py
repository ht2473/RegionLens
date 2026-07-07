"""Тесты служебных эндпойнтов: `/healthz`, `/readyz` и `/metrics`."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest
from django.test import Client

pytestmark = pytest.mark.django_db


def test_healthz_ok() -> None:
    """Liveness всегда возвращает 200 и статус ok."""
    response = Client().get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_readyz_ready_when_dependencies_available(
    settings: pytest.FixtureRequest, tmp_path: Path
) -> None:
    """При доступных PostgreSQL и DuckDB readiness возвращает 200 и все проверки ok."""
    duck_path = tmp_path / "ready.duckdb"
    duckdb.connect(str(duck_path)).close()  # создать валидную витрину
    settings.DUCKDB_PATH = str(duck_path)

    response = Client().get("/readyz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"]["database"] == "ok"
    assert body["checks"]["duckdb"] == "ok"


def test_readyz_not_ready_when_duckdb_missing(
    settings: pytest.FixtureRequest, tmp_path: Path
) -> None:
    """Если DuckDB недоступен — readiness возвращает 503, а БД при этом ok."""
    settings.DUCKDB_PATH = str(tmp_path / "missing.duckdb")

    response = Client().get("/readyz")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["database"] == "ok"
    assert body["checks"]["duckdb"] == "error"


def test_metrics_endpoint_exposes_prometheus() -> None:
    """Эндпойнт /metrics отдаёт метрики в формате Prometheus."""
    response = Client().get("/metrics")
    assert response.status_code == 200
    assert b"# HELP" in response.content
