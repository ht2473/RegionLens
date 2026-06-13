"""Тесты модуля разброса/неравенства (pipeline.dispersion).

Проверяют арифметику разброса на детерминированной синтетике без обращения к данным:
корректность статистик, гейтинг cv/P90-P10 по шкале value_type, предохранители на
неположительные mean/p10, отсев малых групп и соответствие контракту.
"""

import polars as pl
import pytest

from pipeline.dispersion import DISPERSION_SCHEMA, compute_dispersion, run_dispersion


def _features_wide(rows: list[tuple[str, int, int, float]]) -> pl.DataFrame:
    """Синтетический features_wide из строк (okato, year, metric_id, value_harmonized)."""
    return pl.DataFrame(
        rows,
        schema=["okato", "year", "metric_id", "value_harmonized"],
        orient="row",
    ).with_columns(pl.col("year").cast(pl.Int32), pl.col("metric_id").cast(pl.Int32))


def _metric_dim(types: dict[int, str]) -> pl.DataFrame:
    """Синтетический metric_dim: metric_id → value_type."""
    return pl.DataFrame(
        {"metric_id": list(types), "value_type": list(types.values())}
    ).with_columns(pl.col("metric_id").cast(pl.Int32))


def _rows(metric_id: int, year: int, values: list[float]) -> list[tuple[str, int, int, float]]:
    """Строки для одной (метрики, года): по региону на значение."""
    return [(f"{i + 1:02d}", year, metric_id, v) for i, v in enumerate(values)]


def test_basic_statistics_ratio_metric() -> None:
    """Базовые статистики и cv/ratio для метрики со шкалой отношений (per_capita)."""
    fw = _features_wide(_rows(1, 2020, [10.0, 20.0, 30.0, 40.0, 50.0]))
    md = _metric_dim({1: "per_capita"})
    row = compute_dispersion(fw, md, min_regions=2).to_dicts()[0]

    assert row["metric_id"] == 1
    assert row["year"] == 2020
    assert row["n_regions"] == 5
    assert row["mean"] == pytest.approx(30.0)
    assert row["median"] == pytest.approx(30.0)
    assert row["std"] == pytest.approx(250.0**0.5)  # выборочное std, ddof=1
    assert row["p10"] == pytest.approx(14.0)
    assert row["p90"] == pytest.approx(46.0)
    assert row["iqr"] == pytest.approx(20.0)
    assert row["value_range"] == pytest.approx(40.0)
    assert row["cv"] == pytest.approx((250.0**0.5) / 30.0)
    assert row["p90_p10_ratio"] == pytest.approx(46.0 / 14.0)


def test_cv_and_ratio_null_for_non_ratio_scale() -> None:
    """Для index/rate_yoy (произвольный ноль) cv и P90/P10 — NULL, но разброс считается."""
    values = [10.0, 20.0, 30.0, 40.0, 50.0]
    md = _metric_dim({2: "index", 3: "rate_yoy"})
    fw = _features_wide(_rows(2, 2020, values) + _rows(3, 2020, values))
    rows = {r["metric_id"]: r for r in compute_dispersion(fw, md, min_regions=2).to_dicts()}

    for mid in (2, 3):
        assert rows[mid]["cv"] is None
        assert rows[mid]["p90_p10_ratio"] is None
        # шкало-независимый разброс всё равно посчитан
        assert rows[mid]["std"] == pytest.approx(250.0**0.5)
        assert rows[mid]["iqr"] == pytest.approx(20.0)


def test_ratio_guard_on_nonpositive_p10() -> None:
    """Шкала отношений, но p10<=0: P90/P10 — NULL; cv считается, т.к. mean>0."""
    fw = _features_wide(_rows(1, 2020, [-5.0, 0.0, 10.0, 20.0, 30.0]))
    md = _metric_dim({1: "per_capita"})
    row = compute_dispersion(fw, md, min_regions=2).to_dicts()[0]

    assert row["mean"] == pytest.approx(11.0)
    assert row["p10"] == pytest.approx(-3.0)
    assert row["p90_p10_ratio"] is None  # p10 ≤ 0 → отношение не считаем
    assert row["cv"] == pytest.approx((820.0 / 4.0) ** 0.5 / 11.0)  # mean > 0 → cv есть


def test_min_regions_filters_small_groups() -> None:
    """Группы с числом регионов меньше min_regions отбрасываются."""
    fw = _features_wide(_rows(1, 2020, [10.0, 20.0, 30.0, 40.0, 50.0]))  # n=5
    md = _metric_dim({1: "per_capita"})

    assert compute_dispersion(fw, md, min_regions=5).height == 1
    assert compute_dispersion(fw, md, min_regions=6).height == 0


def test_spread_widening_across_years() -> None:
    """Описательно: при более широком разбросе в следующем году std/cv растут."""
    fw = _features_wide(
        _rows(1, 2020, [10.0, 20.0, 30.0, 40.0, 50.0])
        + _rows(1, 2021, [10.0, 20.0, 30.0, 40.0, 90.0])
    )
    md = _metric_dim({1: "per_capita"})
    by_year = {r["year"]: r for r in compute_dispersion(fw, md, min_regions=2).to_dicts()}

    assert by_year[2021]["std"] > by_year[2020]["std"]
    assert by_year[2021]["cv"] > by_year[2020]["cv"]


def test_contract_columns_and_types() -> None:
    """Результат соответствует контракту DISPERSION_SCHEMA по составу и типам колонок."""
    fw = _features_wide(_rows(1, 2020, [10.0, 20.0, 30.0, 40.0, 50.0]))
    md = _metric_dim({1: "per_capita"})
    disp = compute_dispersion(fw, md, min_regions=2)

    assert disp.columns == list(DISPERSION_SCHEMA)
    assert dict(zip(disp.columns, disp.dtypes, strict=True)) == DISPERSION_SCHEMA


def test_run_dispersion_reads_config_and_returns_table() -> None:
    """run_dispersion(write=False) применяет порог из конфига и возвращает таблицу."""
    fw = _features_wide(_rows(1, 2020, [10.0, 20.0, 30.0, 40.0, 50.0]))  # n=5 ≥ конфиг(5)
    md = _metric_dim({1: "per_capita"})
    result = run_dispersion(fw, md, write=False)

    assert result.dispersion.height == 1
    assert result.dispersion["metric_id"].to_list() == [1]
