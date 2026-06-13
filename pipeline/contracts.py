"""Контракты таблиц DuckDB — единый источник схем (REFERENCE §2).

Схемы контрактных таблиц собраны здесь, чтобы не дублироваться по модулям конвейера.
Polars-схемы (отображение столбец→тип) задают порядок и типы колонок при сборке DataFrame;
pandera-схема валидирует таблицу на выходе стадии: «падение валидации = падение конвейера».
"""

import pandera.polars as pa
import polars as pl
from pandera import Check

# Контракт region_twins (C2): порядок и типы колонок top-N двойников на регион-год.
TWINS_SCHEMA = {
    "okato": pl.Utf8,
    "year": pl.Int32,
    "twin_okato": pl.Utf8,
    "similarity": pl.Float64,
    "rank": pl.Int32,
}

# Контракт anomalies (Ф9): metric_id NULL для пространственных выбросов.
ANOMALIES_SCHEMA = {
    "okato": pl.Utf8,
    "metric_id": pl.Int32,
    "year": pl.Int32,
    "score": pl.Float64,
    "is_anomaly": pl.Boolean,
    "kind": pl.Utf8,
}

# Контракт dispersion (Ф13): разброс value_harmonized по регионам на (метрику, год).
DISPERSION_SCHEMA = {
    "metric_id": pl.Int32,
    "year": pl.Int32,
    "n_regions": pl.Int32,
    "mean": pl.Float64,
    "median": pl.Float64,
    "std": pl.Float64,
    "p10": pl.Float64,
    "p90": pl.Float64,
    "iqr": pl.Float64,
    "value_range": pl.Float64,
    "cv": pl.Float64,
    "p90_p10_ratio": pl.Float64,
}

# Контракт fact_region (S2): типы + год в допустимом диапазоне. coerce приводит типы к схеме.
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
