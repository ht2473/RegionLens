"""Тесты статистических двойников (фича C2): косинусная близость профилей по z_value."""

from __future__ import annotations

import numpy as np
import polars as pl

from pipeline.twins import build_year_matrix, cosine_matrix, run_twins, twins_for_year


def _features_wide() -> pl.DataFrame:
    """4 региона × 2 метрики, 2 года. Профили (по z_value) подобраны так, что A и B
    сонаправлены (cos≈1), C противоположен A (cos≈−1), D ортогонален A (cos≈0). Во втором
    году значения масштабированы ×1.5 — отношения (а значит и двойники) сохраняются.
    """
    base = {"A": [2.0, 1.0], "B": [1.0, 0.5], "C": [-2.0, -1.0], "D": [1.0, -2.0]}
    rows: list[dict[str, object]] = []
    for year, scale in ((2010, 1.0), (2011, 1.5)):
        for okato, vec in base.items():
            for metric_id, z in zip((10, 20), vec, strict=True):
                rows.append(
                    {
                        "okato": okato,
                        "year": year,
                        "metric_id": metric_id,
                        "value_harmonized": 0.0,
                        "z_value": z * scale,
                        "is_imputed": False,
                    }
                )
    return pl.DataFrame(rows)


def test_cosine_matrix_known_values() -> None:
    """Косинус сонаправленных = 1, противоположных = −1, ортогональных = 0; диагональ = 1."""
    m = np.array([[2.0, 1.0], [1.0, 0.5], [-2.0, -1.0], [1.0, -2.0]])
    sim = cosine_matrix(m)
    assert sim.shape == (4, 4)
    assert np.allclose(np.diag(sim), 1.0)
    assert abs(sim[0, 1] - 1.0) < 1e-9
    assert abs(sim[0, 2] - (-1.0)) < 1e-9
    assert abs(sim[0, 3]) < 1e-9


def test_build_year_matrix_order_and_shape() -> None:
    """Строки — регионы по okato (детерминированно), столбцы — метрики ядра по числовому id."""
    okatos, matrix = build_year_matrix(_features_wide(), 2010)
    assert okatos == ["A", "B", "C", "D"]
    assert matrix.shape == (4, 2)
    assert matrix[0].tolist() == [2.0, 1.0]  # регион A: metric 10 → 2.0, metric 20 → 1.0


def test_twins_ranking_self_excluded_and_range() -> None:
    """Для A ближайший — B, затем D; сам регион не попадает; similarity ∈ [−1;1]."""
    okatos, matrix = build_year_matrix(_features_wide(), 2010)
    rows = twins_for_year(okatos, cosine_matrix(matrix), 2010, top_n=2)
    a_rows = sorted((r for r in rows if r["okato"] == "A"), key=lambda r: r["rank"])  # type: ignore[index,return-value]
    assert [r["twin_okato"] for r in a_rows] == ["B", "D"]
    assert a_rows[0]["rank"] == 1 and a_rows[1]["rank"] == 2
    assert all(r["twin_okato"] != r["okato"] for r in rows)
    assert all(-1.0 - 1e-9 <= float(r["similarity"]) <= 1.0 + 1e-9 for r in rows)  # type: ignore[arg-type]


def test_run_twins_schema_count_and_determinism() -> None:
    """run_twins: контракт колонок, число строк = регионы×top_n×годы, ровно top_n на пару,
    детерминизм (повторный прогон идентичен)."""
    fw = _features_wide()
    out1 = run_twins(fw, write=False, top_n=2).twins
    assert out1.columns == ["okato", "year", "twin_okato", "similarity", "rank"]
    assert out1.height == 4 * 2 * 2  # 4 региона × 2 двойника × 2 года
    per = out1.group_by(["okato", "year"]).len()
    assert per["len"].unique().to_list() == [2]
    out2 = run_twins(fw, write=False, top_n=2).twins
    assert out1.equals(out2)
