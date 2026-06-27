"""Тесты разброса индекса / σ-сходимости (pipeline.index_dispersion).

Детерминированная синтетика с вручную посчитанными мерами разброса (cv, gini, p90/p10),
проверка контракта и порога минимального числа регионов.
"""

import polars as pl
import pytest

from pipeline.contracts import INDEX_DISPERSION_SCHEMA
from pipeline.index_dispersion import compute_index_dispersion, run_index_dispersion


def _dev_index(rows: list[tuple[str, int, str, float]]) -> pl.DataFrame:
    """rows: (okato, year, weighting_scheme, total_score)."""
    return pl.DataFrame(
        rows, schema=["okato", "year", "weighting_scheme", "total_score"], orient="row"
    ).with_columns(pl.col("year").cast(pl.Int32))


# 5 регионов, баллы 10..50 (mean=30, std=sqrt(200)≈14.142):
#   cv = 14.142/30 ≈ 0.4714; p10=14, p90=46 → p90/p10 ≈ 3.2857;
#   gini = 200/(5*150) ≈ 0.2667
_ROWS = [
    ("A", 2020, "equal", 10.0),
    ("B", 2020, "equal", 20.0),
    ("C", 2020, "equal", 30.0),
    ("D", 2020, "equal", 40.0),
    ("E", 2020, "equal", 50.0),
]


def test_dispersion_measures() -> None:
    """cv, gini, p90/p10, mean, std совпадают с ручным расчётом."""
    row = compute_index_dispersion(_dev_index(_ROWS)).to_dicts()[0]
    assert row["n_regions"] == 5
    assert row["mean"] == pytest.approx(30.0)
    assert row["std"] == pytest.approx(14.1421356, rel=1e-5)
    assert row["cv"] == pytest.approx(0.4714045, rel=1e-5)
    assert row["p90_p10"] == pytest.approx(46.0 / 14.0, rel=1e-5)
    assert row["gini"] == pytest.approx(0.2666667, rel=1e-5)


def test_below_min_regions_skipped() -> None:
    """Группа менее 5 регионов в расчёт не идёт."""
    rows = [
        ("A", 2021, "equal", 10.0),
        ("B", 2021, "equal", 20.0),
        ("C", 2021, "equal", 30.0),
        ("D", 2021, "equal", 40.0),
    ]  # 4 региона
    assert compute_index_dispersion(_dev_index(rows)).height == 0


def test_contract_columns_and_types() -> None:
    """Результат соответствует контракту INDEX_DISPERSION_SCHEMA по составу и типам."""
    out = compute_index_dispersion(_dev_index(_ROWS))
    assert out.columns == list(INDEX_DISPERSION_SCHEMA)
    assert dict(zip(out.columns, out.dtypes, strict=True)) == INDEX_DISPERSION_SCHEMA


def test_run_returns_table() -> None:
    """run_index_dispersion(write=False) возвращает строку на (схема, год)."""
    result = run_index_dispersion(_dev_index(_ROWS), write=False)
    assert result.index_dispersion.height == 1
