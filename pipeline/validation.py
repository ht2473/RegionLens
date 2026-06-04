"""pandera-валидация контрактных таблиц и отчёт качества данных (Ф1, S2).

Принцип Хартии: «падение валидации = падение конвейера» — никаких тихих грязных данных.
"""

from typing import Any, cast

import pandera.polars as pa
import polars as pl
from pandera import Check

from pipeline.logging_setup import log

# Уникальная грань факта (правило грани 3): okato × metric_id × year.
GRAIN = ["okato", "metric_id", "year"]

# Схема fact_region: типы + год в допустимом диапазоне. coerce приводит типы к схеме.
FACT_REGION_SCHEMA = pa.DataFrameSchema(
    {
        "okato": pa.Column(pl.String),
        "metric_id": pa.Column(pl.Int32),
        "year": pa.Column(pl.Int64, Check.in_range(2001, 2025)),
        "value": pa.Column(pl.Float64, nullable=True),
        "source": pa.Column(pl.String, nullable=True),
    },
    coerce=True,
)


def validate_fact_region(fact: pl.DataFrame) -> pl.DataFrame:
    """Проверить fact_region; при нарушении бросает исключение (конвейер падает).

    Проверяется: типы колонок, year ∈ [2001, 2025], уникальность грани
    (okato, metric_id, year). Возвращает провалидированный (приведённый) DataFrame.
    """
    validated: pl.DataFrame = FACT_REGION_SCHEMA.validate(fact, lazy=False)
    dups = validated.height - validated.select(GRAIN).unique().height
    if dups:
        raise ValueError(f"Нарушена уникальность грани {GRAIN}: дублей {dups}")
    return validated


def quality_report(
    fact: pl.DataFrame, metric_dim: pl.DataFrame, region_dim: pl.DataFrame
) -> dict[str, Any]:
    """Сводка качества слоя данных (пишется в лог): объёмы, метрики, регионы, годы."""
    report: dict[str, Any] = {
        "fact_rows": fact.height,
        "n_metrics": metric_dim.height,
        "n_regions": region_dim.height,
        "n_regions_included": region_dim.filter(pl.col("included_flag")).height,
        "year_min": int(cast(int, fact["year"].min())),
        "year_max": int(cast(int, fact["year"].max())),
    }
    log.info("quality_report", stage="etl", **report)
    return report
