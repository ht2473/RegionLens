"""Тесты модуля стабильности рейтинга (pipeline.rank_stability).

Проверяют арифметику устойчивости ранга на детерминированной синтетике без обращения к
данным: соответствие ранга соглашению рейтинга (по убыванию total_score), статистики
волатильности, отсев коротких рядов (min_years), независимость по схемам и контракт.
"""

import polars as pl
import pytest

from pipeline.contracts import RANK_STABILITY_SCHEMA
from pipeline.rank_stability import compute_rank_stability, run_rank_stability


def _dev_index(rows: list[tuple[str, int, str, float]]) -> pl.DataFrame:
    """Синтетический dev_index из строк (okato, year, weighting_scheme, total_score)."""
    return pl.DataFrame(
        rows,
        schema=["okato", "year", "weighting_scheme", "total_score"],
        orient="row",
    ).with_columns(pl.col("year").cast(pl.Int32), pl.col("total_score").cast(pl.Float64))


# Ранги по схеме «equal»: A всегда 1-й, B и C меняются местами 2↔3.
#   2018: A=100 B=90 C=80 → A1 B2 C3
#   2019: A=100 B=70 C=90 → A1 C2 B3  (B=3, C=2)
#   2020: A=100 B=85 C=80 → A1 B2 C3
_THREE = [
    ("A", 2018, "equal", 100.0),
    ("B", 2018, "equal", 90.0),
    ("C", 2018, "equal", 80.0),
    ("A", 2019, "equal", 100.0),
    ("B", 2019, "equal", 70.0),
    ("C", 2019, "equal", 90.0),
    ("A", 2020, "equal", 100.0),
    ("B", 2020, "equal", 85.0),
    ("C", 2020, "equal", 80.0),
]


def test_rank_follows_index_order_and_stable_region() -> None:
    """Высший total_score → ранг 1; стабильный регион имеет нулевой разброс ранга."""
    out = compute_rank_stability(_dev_index(_THREE), min_years=2)
    rows = {r["okato"]: r for r in out.to_dicts()}

    a = rows["A"]  # ранги [1,1,1]
    assert a["n_years"] == 3
    assert a["rank_mean"] == pytest.approx(1.0)
    assert a["rank_std"] == pytest.approx(0.0)
    assert a["rank_min"] == 1 and a["rank_max"] == 1
    assert a["rank_range"] == 0
    assert a["mean_abs_change"] == pytest.approx(0.0)


def test_volatility_statistics() -> None:
    """Для региона с рангами [2,3,2] статистики волатильности считаются точно."""
    out = compute_rank_stability(_dev_index(_THREE), min_years=2)
    b = next(r for r in out.to_dicts() if r["okato"] == "B")  # ранги [2,3,2]

    assert b["rank_mean"] == pytest.approx(7 / 3)
    assert b["rank_std"] == pytest.approx((1 / 3) ** 0.5)  # выборочное std [2,3,2]
    assert b["rank_min"] == 2 and b["rank_max"] == 3
    assert b["rank_range"] == 1
    assert b["mean_abs_change"] == pytest.approx(1.0)  # (|3-2| + |2-3|) / 2


def test_output_sorted_most_stable_first() -> None:
    """Результат упорядочен по rank_std: самый стабильный регион — первым."""
    out = compute_rank_stability(_dev_index(_THREE), min_years=2)
    assert out["okato"].to_list()[0] == "A"  # rank_std = 0


def test_min_years_filters_short_series() -> None:
    """Регион менее чем с min_years годами с рангом отбрасывается."""
    rows = [
        ("A", 2018, "equal", 90.0),
        ("B", 2018, "equal", 80.0),
        ("C", 2018, "equal", 70.0),
        ("A", 2019, "equal", 90.0),
        ("B", 2019, "equal", 80.0),
        ("C", 2019, "equal", 70.0),
        ("A", 2020, "equal", 90.0),
        ("B", 2020, "equal", 80.0),  # C отсутствует в 2020
    ]
    di = _dev_index(rows)
    got3 = {r["okato"] for r in compute_rank_stability(di, min_years=3).to_dicts()}
    got2 = {r["okato"] for r in compute_rank_stability(di, min_years=2).to_dicts()}
    assert got3 == {"A", "B"}
    assert got2 == {"A", "B", "C"}


def test_schemes_are_independent() -> None:
    """Ранг и устойчивость считаются по каждой схеме весов отдельно."""
    rows = [
        ("A", 2018, "equal", 90.0),
        ("B", 2018, "equal", 80.0),
        ("A", 2019, "equal", 90.0),
        ("B", 2019, "equal", 80.0),
        # в схеме pca порядок обратный
        ("A", 2018, "pca", 10.0),
        ("B", 2018, "pca", 80.0),
        ("A", 2019, "pca", 10.0),
        ("B", 2019, "pca", 80.0),
    ]
    out = compute_rank_stability(_dev_index(rows), min_years=2)
    by_key = {(r["okato"], r["weighting_scheme"]): r for r in out.to_dicts()}

    assert by_key[("A", "equal")]["rank_mean"] == pytest.approx(1.0)  # A лидер в equal
    assert by_key[("A", "pca")]["rank_mean"] == pytest.approx(2.0)  # A последний в pca
    assert {scheme for _, scheme in by_key} == {"equal", "pca"}


def test_contract_columns_and_types() -> None:
    """Результат соответствует контракту RANK_STABILITY_SCHEMA по составу и типам колонок."""
    out = compute_rank_stability(_dev_index(_THREE), min_years=2)
    assert out.columns == list(RANK_STABILITY_SCHEMA)
    assert dict(zip(out.columns, out.dtypes, strict=True)) == RANK_STABILITY_SCHEMA


def test_run_rank_stability_reads_config_and_returns_table() -> None:
    """run_rank_stability(write=False) применяет порог из конфига и возвращает таблицу."""
    result = run_rank_stability(_dev_index(_THREE), write=False)  # 3 года ≥ конфиг(3)
    assert result.rank_stability.height == 3
    assert set(result.rank_stability["okato"].to_list()) == {"A", "B", "C"}
