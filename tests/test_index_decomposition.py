"""Тесты декомпозиции индекса (pipeline.index_decomposition).

Главное проверяемое свойство — честность разложения: сумма вкладов доменов в точности равна
годовому изменению индекса (delta_total_score). Плюс ручной пример с равными весами, отсев
первого года и несоседних лет, нулевое изменение и контракт. Без обращения к данным.
"""

import numpy as np
import polars as pl
import pytest

from pipeline.contracts import INDEX_DECOMPOSITION_SCHEMA
from pipeline.index_decomposition import (
    compute_index_decomposition,
    decompose_for_weights,
    run_index_decomposition,
)


def _toy_inputs() -> tuple[pl.DataFrame, pl.DataFrame]:
    """Синтетические features_wide + metric_dim: 5 регионов, 3 года, 3 домена (по метрике)."""
    rows = []
    for ri in range(5):
        ok = f"{ri + 1:02d}"
        for y in (2018, 2019, 2020):
            z1 = ri * 0.4 - 0.8 + 0.2 * (y - 2019)
            z2 = -ri * 0.3 + 0.5 - 0.1 * (y - 2019)
            z3 = (ri % 2) * 0.6 - 0.3 + 0.15 * (y - 2018)
            rows.append({"okato": ok, "year": y, "metric_id": 1, "z_value": z1})
            rows.append({"okato": ok, "year": y, "metric_id": 2, "z_value": z2})
            rows.append({"okato": ok, "year": y, "metric_id": 3, "z_value": z3})
    fw = pl.DataFrame(rows).with_columns(
        pl.col("year").cast(pl.Int32), pl.col("metric_id").cast(pl.Int32)
    )
    md = pl.DataFrame(
        {
            "metric_id": [1, 2, 3],
            "domain": ["economy", "income", "labor"],
            "higher_is_better": [True, True, True],
        }
    ).with_columns(pl.col("metric_id").cast(pl.Int32))
    return fw, md


def _equal_scored() -> pl.DataFrame:
    """Готовые доменные баллы + итог: регион 01 растёт за счёт economy, 02 — за счёт income."""
    return pl.DataFrame(
        {
            "okato": ["01", "01", "02", "02"],
            "year": [2019, 2020, 2019, 2020],
            "economy": [0.0, 2.0, 0.0, 0.0],
            "income": [0.0, 0.0, 0.0, 2.0],
            "total_score": [0.0, 100.0, 0.0, 100.0],
        }
    ).with_columns(pl.col("year").cast(pl.Int32))


def test_equal_weight_decomposition_hand_example() -> None:
    """Ручной пример: весь годовой прирост индекса приписан изменившемуся домену."""
    out = decompose_for_weights(
        _equal_scored(), ["economy", "income"], "equal", np.array([0.5, 0.5])
    )
    assert out.height == 4  # 2 региона × 2 домена × 1 год (2019 — первый, исключён)
    by = {(r["okato"], r["domain"]): r for r in out.to_dicts()}
    assert by[("01", "economy")]["contribution"] == pytest.approx(100.0)
    assert by[("01", "income")]["contribution"] == pytest.approx(0.0)
    assert by[("01", "economy")]["delta_total_score"] == pytest.approx(100.0)
    assert by[("01", "economy")]["domain_delta"] == pytest.approx(2.0)
    assert by[("01", "economy")]["weight"] == pytest.approx(0.5)
    assert by[("02", "income")]["contribution"] == pytest.approx(100.0)
    assert by[("02", "economy")]["contribution"] == pytest.approx(0.0)


def test_contributions_sum_to_delta_total() -> None:
    """Честность разложения: сумма вкладов доменов = delta_total_score (для каждой схемы)."""
    fw, md = _toy_inputs()
    dec = compute_index_decomposition(fw, md)
    grouped = dec.group_by(["okato", "year", "weighting_scheme"]).agg(
        pl.col("contribution").sum().alias("sum_contrib"),
        pl.col("delta_total_score").first().alias("delta"),
    )
    for r in grouped.iter_rows(named=True):
        assert r["sum_contrib"] == pytest.approx(r["delta"], abs=1e-6)


def test_first_year_has_no_decomposition() -> None:
    """Для первого года изменение не определено → строк декомпозиции нет."""
    fw, md = _toy_inputs()
    dec = compute_index_decomposition(fw, md)
    assert dec["year"].min() == 2019  # 2018 — первый год выборки


def test_non_consecutive_years_skipped() -> None:
    """Несоседние годы (пропуск) не дают строки декомпозиции."""
    scored = pl.DataFrame(
        {
            "okato": ["01", "01"],
            "year": [2015, 2018],
            "economy": [0.0, 1.0],
            "income": [0.0, 1.0],
            "total_score": [0.0, 50.0],
        }
    ).with_columns(pl.col("year").cast(pl.Int32))
    out = decompose_for_weights(scored, ["economy", "income"], "equal", np.array([0.5, 0.5]))
    assert out.height == 0


def test_zero_change_gives_zero_contributions() -> None:
    """Если индекс и доменные баллы не изменились — вклады нулевые."""
    scored = pl.DataFrame(
        {
            "okato": ["01", "01"],
            "year": [2019, 2020],
            "economy": [1.0, 1.0],
            "income": [2.0, 2.0],
            "total_score": [50.0, 50.0],
        }
    ).with_columns(pl.col("year").cast(pl.Int32))
    out = decompose_for_weights(scored, ["economy", "income"], "equal", np.array([0.5, 0.5]))
    assert all(c == 0.0 for c in out["contribution"].to_list())
    assert all(d == 0.0 for d in out["delta_total_score"].to_list())


def test_contract_columns_and_types() -> None:
    """Результат соответствует контракту INDEX_DECOMPOSITION_SCHEMA по составу и типам колонок."""
    fw, md = _toy_inputs()
    out = compute_index_decomposition(fw, md)
    assert out.columns == list(INDEX_DECOMPOSITION_SCHEMA)
    assert dict(zip(out.columns, out.dtypes, strict=True)) == INDEX_DECOMPOSITION_SCHEMA


def test_run_index_decomposition_returns_table() -> None:
    """run_index_decomposition(write=False) возвращает непустую таблицу со схемами весов."""
    fw, md = _toy_inputs()
    result = run_index_decomposition(fw, md, write=False)
    assert result.index_decomposition.height > 0
    assert "equal" in set(result.index_decomposition["weighting_scheme"].to_list())
