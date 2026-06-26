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

# Контракт rank_stability (Ф14): волатильность ранга региона по индексу за годы.
RANK_STABILITY_SCHEMA = {
    "okato": pl.Utf8,
    "weighting_scheme": pl.Utf8,
    "n_years": pl.Int32,
    "rank_mean": pl.Float64,
    "rank_std": pl.Float64,
    "rank_min": pl.Int32,
    "rank_max": pl.Int32,
    "rank_range": pl.Int32,
    "mean_abs_change": pl.Float64,
}

# Контракт correlations (Ф15): парные корреляции метрик по регионам на год.
CORRELATIONS_SCHEMA = {
    "year": pl.Int32,
    "metric_a": pl.Int32,
    "metric_b": pl.Int32,
    "method": pl.Utf8,
    "correlation": pl.Float64,
    "n_regions": pl.Int32,
}

# Контракт index_decomposition (Ф16): вклад доменов в годовое изменение индекса.
INDEX_DECOMPOSITION_SCHEMA = {
    "okato": pl.Utf8,
    "year": pl.Int32,
    "weighting_scheme": pl.Utf8,
    "domain": pl.Utf8,
    "delta_total_score": pl.Float64,
    "domain_delta": pl.Float64,
    "weight": pl.Float64,
    "contribution": pl.Float64,
}

# Контракт metric_catalog: тиринг и профиль ВСЕХ метрик каталога (а не только ядра).
# Грань — metric_id. tier: core (ядро индекса/типологии) / extended (вне ядра, но хорошо покрыты —
# доступны для explore) / sparse (слишком разрежены). year_min/max/n_years/n_regions — фактический
# охват по сырью (полное окно 2001–2025), coverage — оконное покрытие из metric_dim. Основа explore
# и будущего расширения ядра; ничего не считает заново — агрегирует уже готовые таблицы.
METRIC_CATALOG_SCHEMA = {
    "metric_id": pl.Int32,
    "indicator_code": pl.Utf8,
    "metric_name": pl.Utf8,
    "domain": pl.Utf8,
    "value_type": pl.Utf8,
    "unit": pl.Utf8,
    "coverage": pl.Float64,
    "year_min": pl.Int32,
    "year_max": pl.Int32,
    "n_years": pl.Int32,
    "n_regions": pl.Int32,
    "is_core": pl.Boolean,
    "tier": pl.Utf8,
}

# Контракт data_quality (Ф17): полнота/импутации аналитической сетки на (метрику, год).
# Грань — (metric_id, year) по сетке ядра. n_regions — число ячеек сетки (включённые регионы);
# n_present_raw — из них с непустым СЫРЫМ значением (доступность источника, до гармонизации);
# n_imputed — достроенные ячейки ГАРМОНИЗИРОВАННОЙ сетки. Для absolute-метрик raw-полнота может
# превышать (1 − impute_share): сырьё было, но гармонизация (деление на население) дала пропуск.
DATA_QUALITY_SCHEMA = {
    "metric_id": pl.Int32,
    "year": pl.Int32,
    "n_regions": pl.Int32,
    "n_present_raw": pl.Int32,
    "n_imputed": pl.Int32,
    "completeness_raw": pl.Float64,
    "impute_share": pl.Float64,
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
