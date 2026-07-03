"""Тесты pandera-валидации fact_region и отчёта качества."""

from __future__ import annotations

import polars as pl
import pytest
from pandera.errors import SchemaError

from pipeline.validation import quality_report, validate_fact_region


def _clean_fact() -> pl.DataFrame:
    """Чистый сэмпл fact_region (две разные грани)."""
    return pl.DataFrame(
        {
            "okato": ["92000000000", "01000000000"],
            "metric_id": [1, 1],
            "year": [2015, 2015],
            "value": [100.0, None],
            "source": ["Сборник 2021", "Сборник 2021"],
        }
    )


def test_validate_passes_on_clean_sample() -> None:
    """Чистый факт проходит валидацию; metric_id приводится к Int32."""
    out = validate_fact_region(_clean_fact())
    assert out.height == 2
    assert out.schema["metric_id"] == pl.Int32


def test_validate_fails_on_duplicate_grain() -> None:
    """Дубль по грани (okato, metric_id, year) → конвейер падает (ValueError)."""
    dup = pl.DataFrame(
        {
            "okato": ["92000000000", "92000000000"],
            "metric_id": [1, 1],
            "year": [2015, 2015],
            "value": [1.0, 2.0],
            "source": ["s", "s"],
        }
    )
    with pytest.raises(ValueError):
        validate_fact_region(dup)


def test_validate_fails_on_year_out_of_range() -> None:
    """Год вне [2001, 2025] → pandera роняет валидацию (SchemaError)."""
    bad = pl.DataFrame(
        {
            "okato": ["92000000000"],
            "metric_id": [1],
            "year": [2030],
            "value": [1.0],
            "source": ["s"],
        }
    )
    with pytest.raises(SchemaError):
        validate_fact_region(bad)


def test_quality_report_keys() -> None:
    """Отчёт качества содержит ключевые метрики слоя данных."""
    fact = _clean_fact()
    metric_dim = pl.DataFrame({"metric_id": [1]})
    region_dim = pl.DataFrame(
        {"okato": ["92000000000", "01000000000"], "included_flag": [True, True]}
    )
    rep = quality_report(fact, metric_dim, region_dim)
    assert rep["fact_rows"] == 2
    assert rep["n_metrics"] == 1
    assert rep["n_regions_included"] == 2
    assert rep["year_min"] == 2015
    assert rep["year_max"] == 2015
