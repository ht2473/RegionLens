"""Тесты согласованности схем весов (pipeline.scheme_agreement).

Детерминированная синтетика с известной ранговой корреляцией: одинаковый порядок → Спирмен 1,
обратный → −1. Проверяем расчёт по парам, контракт и порог минимального числа регионов.
"""

import polars as pl

from pipeline.contracts import SCHEME_AGREEMENT_SCHEMA
from pipeline.scheme_agreement import compute_scheme_agreement, run_scheme_agreement


def _dev_index(rows: list[tuple[str, int, str, float]]) -> pl.DataFrame:
    """rows: (okato, year, weighting_scheme, total_score)."""
    return pl.DataFrame(
        rows, schema=["okato", "year", "weighting_scheme", "total_score"], orient="row"
    ).with_columns(pl.col("year").cast(pl.Int32))


# 4 региона, 1 год, 3 схемы:
#   equal:  A40 B30 C20 D10   (порядок A>B>C>D)
#   pca:    A4  B3  C2  D1     (тот же порядок)            → Спирмен(equal,pca) = 1
#   expert: A1  B2  C3  D4     (обратный порядок)          → Спирмен(equal,expert) = −1
_ROWS = [
    ("A", 2020, "equal", 40.0),
    ("B", 2020, "equal", 30.0),
    ("C", 2020, "equal", 20.0),
    ("D", 2020, "equal", 10.0),
    ("A", 2020, "pca", 4.0),
    ("B", 2020, "pca", 3.0),
    ("C", 2020, "pca", 2.0),
    ("D", 2020, "pca", 1.0),
    ("A", 2020, "expert", 1.0),
    ("B", 2020, "expert", 2.0),
    ("C", 2020, "expert", 3.0),
    ("D", 2020, "expert", 4.0),
]


def test_spearman_by_pair() -> None:
    """Одинаковый порядок → ρ=1; обратный → ρ=−1; пары неупорядоченные (a<b)."""
    by = {
        (r["scheme_a"], r["scheme_b"]): r
        for r in compute_scheme_agreement(_dev_index(_ROWS)).to_dicts()
    }
    assert by[("equal", "pca")]["spearman"] == 1.0
    assert by[("equal", "expert")]["spearman"] == -1.0
    assert by[("expert", "pca")]["spearman"] == -1.0  # expert обратен equal, pca совпадает
    assert by[("equal", "pca")]["n_regions"] == 4


def test_below_min_regions_skipped() -> None:
    """Год с менее чем 3 совпадающими регионами в расчёт не идёт."""
    rows = [
        ("A", 2021, "equal", 5.0),
        ("B", 2021, "equal", 3.0),
        ("A", 2021, "pca", 5.0),
        ("B", 2021, "pca", 3.0),
    ]  # только 2 региона
    out = compute_scheme_agreement(_dev_index(rows))
    assert out.filter(pl.col("year") == 2021).height == 0


def test_contract_columns_and_types() -> None:
    """Результат соответствует контракту SCHEME_AGREEMENT_SCHEMA по составу и типам."""
    out = compute_scheme_agreement(_dev_index(_ROWS))
    assert out.columns == list(SCHEME_AGREEMENT_SCHEMA)
    assert dict(zip(out.columns, out.dtypes, strict=True)) == SCHEME_AGREEMENT_SCHEMA


def test_run_returns_three_pairs() -> None:
    """run_scheme_agreement(write=False): три пары схем за один год."""
    result = run_scheme_agreement(_dev_index(_ROWS), write=False)
    assert result.scheme_agreement.height == 3
