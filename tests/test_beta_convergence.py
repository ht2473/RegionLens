"""Тесты β-сходимости (pipeline.beta_convergence).

Детерминированная синтетика с точной линейной связью роста и старта: рост = −0.5·старт+10,
поэтому β=−0.5, intercept=10, r=−1, R²=1. Проверяем регрессию, контракт и порог числа регионов.
"""

import polars as pl
import pytest

from pipeline.beta_convergence import compute_beta_convergence, run_beta_convergence
from pipeline.contracts import BETA_CONVERGENCE_SCHEMA


def _dev_index(rows: list[tuple[str, int, str, float]]) -> pl.DataFrame:
    """rows: (okato, year, weighting_scheme, total_score)."""
    return pl.DataFrame(
        rows, schema=["okato", "year", "weighting_scheme", "total_score"], orient="row"
    ).with_columns(pl.col("year").cast(pl.Int32))


# 5 регионов, старт 2010 (10..50) и конец 2024; рост = −0.5·старт+10 (точная линия):
#   init 10 20 30 40 50 → growth 5 0 −5 −10 −15 → fin 15 20 25 30 35
#   ⇒ β=−0.5, intercept=10, r=−1, R²=1
_ROWS = [
    ("A", 2010, "equal", 10.0),
    ("A", 2024, "equal", 15.0),
    ("B", 2010, "equal", 20.0),
    ("B", 2024, "equal", 20.0),
    ("C", 2010, "equal", 30.0),
    ("C", 2024, "equal", 25.0),
    ("D", 2010, "equal", 40.0),
    ("D", 2024, "equal", 30.0),
    ("E", 2010, "equal", 50.0),
    ("E", 2024, "equal", 35.0),
]


def test_beta_regression() -> None:
    """β, intercept, корреляция и R² совпадают с точной линией."""
    row = compute_beta_convergence(_dev_index(_ROWS)).to_dicts()[0]
    assert row["weighting_scheme"] == "equal"
    assert row["year_start"] == 2010 and row["year_end"] == 2024 and row["n_regions"] == 5
    assert row["beta"] == pytest.approx(-0.5, abs=1e-3)
    assert row["intercept"] == pytest.approx(10.0, abs=1e-3)
    assert row["correlation"] == pytest.approx(-1.0, abs=1e-3)
    assert row["r_squared"] == pytest.approx(1.0, abs=1e-3)


def test_below_min_regions_skipped() -> None:
    """Схема с менее чем 5 совпадающими регионами в расчёт не идёт."""
    rows = [
        ("A", 2010, "pca", 10.0),
        ("A", 2024, "pca", 12.0),
        ("B", 2010, "pca", 20.0),
        ("B", 2024, "pca", 18.0),
    ]  # 2 региона
    assert compute_beta_convergence(_dev_index(rows)).height == 0


def test_contract_columns_and_types() -> None:
    """Результат соответствует контракту BETA_CONVERGENCE_SCHEMA по составу и типам."""
    out = compute_beta_convergence(_dev_index(_ROWS))
    assert out.columns == list(BETA_CONVERGENCE_SCHEMA)
    assert dict(zip(out.columns, out.dtypes, strict=True)) == BETA_CONVERGENCE_SCHEMA


def test_run_returns_row_per_scheme() -> None:
    """run_beta_convergence(write=False) возвращает строку на схему."""
    result = run_beta_convergence(_dev_index(_ROWS), write=False)
    assert result.beta_convergence.height == 1
