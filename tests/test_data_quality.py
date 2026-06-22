"""Тесты модуля качества данных (pipeline.data_quality).

Проверяют подсчёт полноты/импутаций на детерминированной синтетике без обращения к данным:
точные счётчики и доли на (метрику, год), расхождение «сырьё ≥ гармонизированное» для
absolute-кейса (импутация при наличии сырья), инвариант совпадения оконного роллапа сырой
полноты с pipeline.features.compute_coverage и соответствие контракту.
"""

import polars as pl
import pytest

from pipeline.contracts import DATA_QUALITY_SCHEMA
from pipeline.data_quality import compute_data_quality, run_data_quality
from pipeline.features import compute_coverage

# Строка features_wide: (okato, year, metric_id, value_harmonized|None, is_imputed)
FWRow = tuple[str, int, int, float | None, bool]
# Строка fact_region: (okato, metric_id, year, value|None)
FRRow = tuple[str, int, int, float | None]


def _features_wide(rows: list[FWRow]) -> pl.DataFrame:
    """Синтетический features_wide (z_value не используется модулем — ставим 0)."""
    return pl.DataFrame(
        [(o, y, m, vh, 0.0, imp) for (o, y, m, vh, imp) in rows],
        schema=["okato", "year", "metric_id", "value_harmonized", "z_value", "is_imputed"],
        orient="row",
    ).with_columns(pl.col("year").cast(pl.Int32), pl.col("metric_id").cast(pl.Int32))


def _fact_region(rows: list[FRRow]) -> pl.DataFrame:
    """Синтетический fact_region (source — формальный, не влияет на подсчёт)."""
    return pl.DataFrame(
        [(o, m, y, v, "s") for (o, m, y, v) in rows],
        schema=["okato", "metric_id", "year", "value", "source"],
        orient="row",
    ).with_columns(pl.col("year").cast(pl.Int32), pl.col("metric_id").cast(pl.Int32))


def test_basic_counts_and_shares() -> None:
    """Точные счётчики и доли на (метрику, год) для непустой сетки с одной импутацией."""
    # 3 региона, год 2020: у 03 сырьё отсутствует (строки нет) → гармонизированное импутировано.
    fw = _features_wide(
        [
            ("01", 2020, 1, 10.0, False),
            ("02", 2020, 1, 20.0, False),
            ("03", 2020, 1, 15.0, True),  # достроено
        ]
    )
    fr = _fact_region([("01", 1, 2020, 10.0), ("02", 1, 2020, 20.0)])  # 03 — нет строки
    row = compute_data_quality(fw, fr).to_dicts()[0]

    assert row["metric_id"] == 1
    assert row["year"] == 2020
    assert row["n_regions"] == 3
    assert row["n_present_raw"] == 2  # сырьё есть у 01 и 02
    assert row["n_imputed"] == 1  # достроен 03
    assert row["completeness_raw"] == pytest.approx(2 / 3)
    assert row["impute_share"] == pytest.approx(1 / 3)


def test_null_raw_value_counts_as_absent() -> None:
    """Строка сырья с value=NULL считается отсутствующей (как и отсутствие строки)."""
    fw = _features_wide([("01", 2020, 1, 10.0, False), ("02", 2020, 1, 12.0, True)])
    fr = _fact_region([("01", 1, 2020, 10.0), ("02", 1, 2020, None)])  # явный NULL у 02
    row = compute_data_quality(fw, fr).to_dicts()[0]

    assert row["n_present_raw"] == 1
    assert row["n_imputed"] == 1
    assert row["completeness_raw"] == pytest.approx(0.5)


def test_raw_present_but_imputed_absolute_case() -> None:
    """Absolute-кейс: сырьё есть, но гармонизированное импутировано (нет населения).

    Тогда сырая полнота строго больше доли не-импутированных: n_present_raw > n_regions − n_imputed.
    """
    fw = _features_wide(
        [
            ("01", 2020, 1, 100.0, False),
            ("02", 2020, 1, 90.0, True),  # импутировано, хотя сырьё ниже есть
        ]
    )
    fr = _fact_region([("01", 1, 2020, 100.0), ("02", 1, 2020, 5000.0)])  # сырьё у обоих
    row = compute_data_quality(fw, fr).to_dicts()[0]

    assert row["n_present_raw"] == 2  # сырьё у обоих
    assert row["n_imputed"] == 1  # но один достроен
    n_present_harmonized = row["n_regions"] - row["n_imputed"]
    assert row["n_present_raw"] > n_present_harmonized  # расхождение двух полнот
    assert row["completeness_raw"] == pytest.approx(1.0)
    assert row["impute_share"] == pytest.approx(0.5)


def test_window_rollup_matches_compute_coverage() -> None:
    """Инвариант: оконный роллап сырой полноты ≡ metric_dim.coverage (compute_coverage).

    Сетка ядра строится как включённые регионы × окно; сумма n_present_raw / сумма n_regions по
    метрике должна совпасть с покрытием из стадии features (тот же знаменатель и числитель).
    """
    window = [2018, 2019, 2020]
    regions = ["01", "02", "03"]
    region_dim = pl.DataFrame({"okato": regions, "included_flag": [True, True, True]})
    # Сырьё: у 02 пропуск 2019, у 03 нет строки за 2020 — остальное заполнено.
    present = {
        ("01", 2018),
        ("01", 2019),
        ("01", 2020),
        ("02", 2018),
        ("02", 2020),
        ("03", 2018),
        ("03", 2019),
    }
    fr_rows: list[FRRow] = []
    fw_rows: list[FWRow] = []
    for ok in regions:
        for y in window:
            has_raw = (ok, y) in present
            if has_raw:
                fr_rows.append((ok, 1, y, 100.0 + y))
            # сетка ядра прямоугольна: ячейка есть всегда; импутирована, если сырья нет
            vh = 100.0 + y if has_raw else 100.0
            fw_rows.append((ok, y, 1, vh, not has_raw))
    fw = _features_wide(fw_rows)
    fr = _fact_region(fr_rows)

    dq = compute_data_quality(fw, fr)
    present_total = int(dq["n_present_raw"].sum())
    regions_total = int(dq["n_regions"].sum())
    rollup_cov = present_total / regions_total

    cov = compute_coverage(fr, region_dim, window)
    expected = cov.filter(pl.col("metric_id") == 1)["coverage"].to_list()[0]
    assert rollup_cov == pytest.approx(expected)
    assert rollup_cov == pytest.approx(7 / 9)


def test_multiple_metrics_and_years() -> None:
    """Группировка по (метрике, году): отдельные строки, без склейки."""
    fw = _features_wide(
        [
            ("01", 2019, 1, 1.0, False),
            ("01", 2020, 1, 2.0, True),
            ("01", 2020, 2, 3.0, False),
        ]
    )
    fr = _fact_region([("01", 1, 2019, 1.0), ("01", 2, 2020, 3.0)])  # 1@2020 — нет сырья
    by = {(r["metric_id"], r["year"]): r for r in compute_data_quality(fw, fr).to_dicts()}

    assert set(by) == {(1, 2019), (1, 2020), (2, 2020)}
    assert by[(1, 2020)]["n_imputed"] == 1 and by[(1, 2020)]["n_present_raw"] == 0
    assert by[(2, 2020)]["n_imputed"] == 0 and by[(2, 2020)]["n_present_raw"] == 1


def test_contract_columns_and_types() -> None:
    """Результат соответствует контракту DATA_QUALITY_SCHEMA по составу и типам колонок."""
    fw = _features_wide([("01", 2020, 1, 10.0, False), ("02", 2020, 1, 20.0, True)])
    fr = _fact_region([("01", 1, 2020, 10.0)])
    dq = compute_data_quality(fw, fr)

    assert dq.columns == list(DATA_QUALITY_SCHEMA)
    assert dict(zip(dq.columns, dq.dtypes, strict=True)) == DATA_QUALITY_SCHEMA


def test_run_data_quality_returns_table() -> None:
    """run_data_quality(write=False) возвращает непустую таблицу нужной грани."""
    fw = _features_wide([("01", 2020, 1, 10.0, False), ("02", 2020, 1, 20.0, True)])
    fr = _fact_region([("01", 1, 2020, 10.0)])
    result = run_data_quality(fw, fr, write=False)

    assert result.data_quality.height == 1
    assert result.data_quality["n_imputed"].to_list() == [1]
