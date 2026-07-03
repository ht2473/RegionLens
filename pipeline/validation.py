"""pandera-валидация контрактных таблиц и отчёт качества данных (Ф1, S2).

Принцип: падение валидации = падение конвейера — никаких тихих грязных данных.
"""

from typing import Any, cast

import polars as pl

from pipeline.contracts import FACT_REGION_SCHEMA
from pipeline.logging_setup import log

# Уникальная грань факта (правило грани 3): okato × metric_id × year.
GRAIN = ["okato", "metric_id", "year"]


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
