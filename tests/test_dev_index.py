"""Тесты индекса развития (Ф4 / S5): направление, доменные баллы, веса, нормировка."""

from __future__ import annotations

import numpy as np
import polars as pl

from pipeline.dev_index import (
    DOMAIN_COLS,
    build_dev_index,
    compute_domain_scores,
    scheme_weights,
    to_100,
)


def test_compute_domain_scores_applies_direction() -> None:
    """z_signed инвертирует знак для higher_is_better=false; доменный балл = среднее по домену."""
    fw = pl.DataFrame(
        {"okato": ["01", "01"], "year": [2010, 2010], "metric_id": [1, 2], "z_value": [2.0, 1.0]}
    )
    md = pl.DataFrame(
        {"metric_id": [1, 2], "domain": ["income", "income"], "higher_is_better": [True, False]}
    )
    wide = compute_domain_scores(fw, md)
    assert abs(wide.filter(pl.col("okato") == "01")["income"][0] - 0.5) < 1e-9


def test_scheme_weights_equal_and_pca_sum_to_one() -> None:
    """equal — поровну (сумма 1); PCA — нагрузки 1-й компоненты, сумма 1."""
    domains = ["economy", "income", "labor"]
    matrix = np.random.default_rng(0).normal(size=(20, 3))
    eq = scheme_weights(matrix, domains, "equal", {})
    assert np.allclose(eq, 1 / 3) and abs(eq.sum() - 1.0) < 1e-9
    pca = scheme_weights(matrix, domains, "pca", {})
    assert abs(pca.sum() - 1.0) < 1e-9


def test_scheme_weights_expert_renormalized() -> None:
    """Экспертные веса берутся из конфига и перенормируются на присутствующие домены."""
    w = scheme_weights(
        np.zeros((2, 2)), ["economy", "income"], "expert", {"economy": 0.3, "income": 0.1}
    )
    assert np.allclose(w, [0.75, 0.25])


def test_to_100_bounds() -> None:
    """Нормировка: минимум -> 0, максимум -> 100, всё в [0;100]; вырожденный случай -> 50."""
    out = to_100(np.array([-2.0, 0.0, 3.0]))
    assert out.min() == 0.0 and out.max() == 100.0
    assert (out >= 0).all() and (out <= 100).all()
    assert np.allclose(to_100(np.array([5.0, 5.0, 5.0])), 50.0)


def _synthetic() -> tuple[pl.DataFrame, pl.DataFrame]:
    rng = np.random.default_rng(1)
    rows = []
    for ok in ("01", "02", "03", "04"):
        for year in (2010, 2011):
            for mid in (1, 2, 3, 4):
                rows.append(
                    {"okato": ok, "year": year, "metric_id": mid, "z_value": float(rng.normal())}
                )
    fw = pl.DataFrame(rows)
    md = pl.DataFrame(
        {
            "metric_id": [1, 2, 3, 4],
            "domain": ["economy", "economy", "income", "income"],
            "higher_is_better": [True, True, True, False],
        }
    )
    return fw, md


def test_build_dev_index_schemes_and_bounds() -> None:
    """dev_index: строки по всем схемам, total_score в [0;100], контрактные доменные колонки."""
    fw, md = _synthetic()
    dev = build_dev_index(fw, md)
    schemes = set(dev["weighting_scheme"].unique().to_list())
    assert {"equal", "pca", "expert"} <= schemes
    assert dev["total_score"].min() >= 0.0 and dev["total_score"].max() <= 100.0
    assert set(DOMAIN_COLS).issubset(set(dev.columns))
    assert dev.height == len(schemes) * 4 * 2
