"""Тесты модуля корреляций (pipeline.correlations).

Проверяют арифметику на детерминированной синтетике без обращения к данным: точные значения
Spearman/Pearson на сконструированных рядах, верхний треугольник без дублей, отсев коротких
лет и метрик без дисперсии, выбор метода из конфига и контракт.
"""

import polars as pl
import pytest

from pipeline.contracts import CORRELATIONS_SCHEMA
from pipeline.correlations import compute_correlations, run_correlations


def _features_wide(metrics: dict[int, list[float]], year: int = 2020) -> pl.DataFrame:
    """Синтетический features_wide: metric_id → значения по регионам (равной длины)."""
    rows = [
        {"okato": f"{i + 1:02d}", "year": year, "metric_id": mid, "value_harmonized": v}
        for mid, vals in metrics.items()
        for i, v in enumerate(vals)
    ]
    return pl.DataFrame(rows).with_columns(
        pl.col("year").cast(pl.Int32), pl.col("metric_id").cast(pl.Int32)
    )


def _pair(rows: list[dict], a: int, b: int) -> dict:
    return next(r for r in rows if r["metric_a"] == a and r["metric_b"] == b)


def test_perfect_positive_spearman() -> None:
    """Монотонно сонаправленные ряды дают Spearman = +1."""
    fw = _features_wide({1: [1.0, 2.0, 3.0, 4.0, 5.0], 2: [2.0, 4.0, 6.0, 8.0, 10.0]})
    rows = compute_correlations(fw, method="spearman", min_regions=2).to_dicts()
    assert _pair(rows, 1, 2)["correlation"] == pytest.approx(1.0)


def test_perfect_negative_spearman() -> None:
    """Противонаправленные ряды дают Spearman = −1."""
    fw = _features_wide({1: [1.0, 2.0, 3.0, 4.0, 5.0], 3: [5.0, 4.0, 3.0, 2.0, 1.0]})
    rows = compute_correlations(fw, method="spearman", min_regions=2).to_dicts()
    assert _pair(rows, 1, 3)["correlation"] == pytest.approx(-1.0)


def test_pearson_method() -> None:
    """Метод pearson: линейно связанные ряды дают +1, метод проставляется в строке."""
    fw = _features_wide({1: [1.0, 2.0, 3.0, 4.0, 5.0], 2: [2.0, 4.0, 6.0, 8.0, 10.0]})
    rows = compute_correlations(fw, method="pearson", min_regions=2).to_dicts()
    pair = _pair(rows, 1, 2)
    assert pair["correlation"] == pytest.approx(1.0)
    assert pair["method"] == "pearson"


def test_upper_triangle_unique_pairs() -> None:
    """Три метрики → три пары верхнего треугольника, metric_a < metric_b, без дублей."""
    fw = _features_wide({1: [1.0, 2.0, 3.0, 4.0], 2: [4.0, 3.0, 2.0, 1.0], 3: [1.0, 3.0, 2.0, 4.0]})
    rows = compute_correlations(fw, method="spearman", min_regions=2).to_dicts()
    pairs = sorted((r["metric_a"], r["metric_b"]) for r in rows)
    assert pairs == [(1, 2), (1, 3), (2, 3)]


def test_min_regions_filters_year() -> None:
    """Год с числом регионов меньше min_regions пропускается."""
    fw = _features_wide({1: [1.0, 2.0, 3.0], 2: [3.0, 2.0, 1.0]})  # 3 региона
    assert compute_correlations(fw, method="spearman", min_regions=5).height == 0
    assert compute_correlations(fw, method="spearman", min_regions=3).height == 1


def test_zero_variance_metric_skipped() -> None:
    """Пары с метрикой без дисперсии (корреляция не определена) не попадают в результат."""
    fw = _features_wide(
        {1: [1.0, 2.0, 3.0, 4.0, 5.0], 9: [7.0, 7.0, 7.0, 7.0, 7.0]}  # 9 — константа
    )
    rows = compute_correlations(fw, method="spearman", min_regions=2).to_dicts()
    assert all(not (r["metric_a"] == 1 and r["metric_b"] == 9) for r in rows)


def test_invalid_method_raises() -> None:
    """Неизвестный метод корреляции приводит к явной ошибке (fail-fast по конфигу)."""
    fw = _features_wide({1: [1.0, 2.0, 3.0], 2: [3.0, 2.0, 1.0]})
    with pytest.raises(ValueError, match="method"):
        compute_correlations(fw, method="kendall", min_regions=2)


def test_contract_columns_and_types() -> None:
    """Результат соответствует контракту CORRELATIONS_SCHEMA по составу и типам колонок."""
    fw = _features_wide({1: [1.0, 2.0, 3.0, 4.0, 5.0], 2: [2.0, 4.0, 6.0, 8.0, 10.0]})
    out = compute_correlations(fw, method="spearman", min_regions=2)
    assert out.columns == list(CORRELATIONS_SCHEMA)
    assert dict(zip(out.columns, out.dtypes, strict=True)) == CORRELATIONS_SCHEMA


def test_run_correlations_reads_config() -> None:
    """run_correlations(write=False) применяет порог/метод из конфига (min_regions=30)."""
    n = 30
    fw = _features_wide({1: [float(i) for i in range(n)], 2: [float(2 * i) for i in range(n)]})
    result = run_correlations(fw, write=False)
    assert result.correlations.height == 1
    assert result.correlations["correlation"].to_list()[0] == pytest.approx(1.0)
