"""Тесты чувствительности ранга к схеме весов (pipeline.rank_robustness).

Детерминированная синтетика: ранг считается внутри (схема, год), затем по региону за год
берётся коридор по схемам (best/worst/range). Проверяем арифметику и контракт.
"""

import polars as pl

from pipeline.contracts import RANK_ROBUSTNESS_SCHEMA
from pipeline.rank_robustness import compute_rank_robustness, run_rank_robustness


def _dev_index(rows: list[tuple[str, int, str, float]]) -> pl.DataFrame:
    """rows: (okato, year, weighting_scheme, total_score)."""
    return pl.DataFrame(
        rows,
        schema=["okato", "year", "weighting_scheme", "total_score"],
        orient="row",
    ).with_columns(pl.col("year").cast(pl.Int32))


# Три региона, один год, три схемы — ранги намеренно расходятся между схемами:
#   equal:  A=90,B=50,C=10  -> A1 B2 C3
#   pca:    A=10,B=50,C=90  -> C1 B2 A3
#   expert: A=50,B=90,C=10  -> B1 A2 C3
_ROWS = [
    ("A", 2020, "equal", 90.0),
    ("B", 2020, "equal", 50.0),
    ("C", 2020, "equal", 10.0),
    ("A", 2020, "pca", 10.0),
    ("B", 2020, "pca", 50.0),
    ("C", 2020, "pca", 90.0),
    ("A", 2020, "expert", 50.0),
    ("B", 2020, "expert", 90.0),
    ("C", 2020, "expert", 10.0),
]


def test_corridor_across_schemes() -> None:
    """best/worst/range — коридор ранга по схемам; A гуляет 1..3, B 1..2."""
    rr = {r["okato"]: r for r in compute_rank_robustness(_dev_index(_ROWS)).to_dicts()}

    assert rr["A"]["n_schemes"] == 3
    assert rr["A"]["rank_best"] == 1 and rr["A"]["rank_worst"] == 3 and rr["A"]["rank_range"] == 2
    assert rr["B"]["rank_best"] == 1 and rr["B"]["rank_worst"] == 2 and rr["B"]["rank_range"] == 1
    assert rr["C"]["rank_best"] == 1 and rr["C"]["rank_worst"] == 3


def test_rank_mean_and_score_span() -> None:
    """rank_mean — средний ранг по схемам; score_min/max — диапазон балла."""
    rr = {r["okato"]: r for r in compute_rank_robustness(_dev_index(_ROWS)).to_dicts()}

    assert rr["A"]["rank_mean"] == 2.0  # (1+3+2)/3
    assert rr["A"]["score_min"] == 10.0 and rr["A"]["score_max"] == 90.0


def test_robust_region_has_zero_range() -> None:
    """Регион с одинаковым местом во всех схемах — коридор 0 (устойчив)."""
    rows = [
        ("A", 2020, "equal", 90.0),
        ("B", 2020, "equal", 10.0),
        ("A", 2020, "pca", 80.0),
        ("B", 2020, "pca", 5.0),
    ]  # A всегда 1-й, B всегда 2-й
    rr = {r["okato"]: r for r in compute_rank_robustness(_dev_index(rows)).to_dicts()}
    assert rr["A"]["rank_range"] == 0 and rr["B"]["rank_range"] == 0


def test_contract_columns_and_types() -> None:
    """Результат соответствует контракту RANK_ROBUSTNESS_SCHEMA по составу и типам."""
    rr = compute_rank_robustness(_dev_index(_ROWS))
    assert rr.columns == list(RANK_ROBUSTNESS_SCHEMA)
    assert dict(zip(rr.columns, rr.dtypes, strict=True)) == RANK_ROBUSTNESS_SCHEMA


def test_run_returns_table() -> None:
    """run_rank_robustness(write=False) возвращает таблицу по всем регионам года."""
    result = run_rank_robustness(_dev_index(_ROWS), write=False)
    assert result.rank_robustness.height == 3
