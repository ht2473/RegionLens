"""Контракты таблиц DuckDB — единый источник схем.

Схемы контрактных таблиц собраны здесь, чтобы не дублироваться по модулям конвейера.
Polars-схемы (отображение столбец→тип) задают порядок и типы колонок при сборке DataFrame;
pandera-схема валидирует таблицу на выходе стадии: «падение валидации = падение конвейера».
"""

import pandera.polars as pa
import polars as pl
from pandera import Check

# Контракт region_twins: порядок и типы колонок top-N двойников на регион-год.
TWINS_SCHEMA = {
    "okato": pl.Utf8,
    "year": pl.Int32,
    "twin_okato": pl.Utf8,
    "similarity": pl.Float64,
    "rank": pl.Int32,
}

# Контракт anomalies: metric_id NULL для пространственных выбросов.
ANOMALIES_SCHEMA = {
    "okato": pl.Utf8,
    "metric_id": pl.Int32,
    "year": pl.Int32,
    "score": pl.Float64,
    "is_anomaly": pl.Boolean,
    "kind": pl.Utf8,
}

# Контракт dispersion: разброс value_harmonized по регионам на (метрику, год).
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

# Контракт rank_stability: волатильность ранга региона по индексу за годы.
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

# Контракт beta_convergence: β-сходимость индекса по схемам весов (грань weighting_scheme).
# Описательная регрессия изменения индекса (за период) на стартовый уровень по регионам:
# beta<0 — регионы с низким стартом росли быстрее (догоняние). Индекс относительный (z-норм.),
# поэтому это мобильность/возврат к среднему, не абсолютный рост. Не прогноз — закрытая
# арифметика (наклон=cov/var) над готовыми баллами; согласуется со стоп-правилом валидации.
BETA_CONVERGENCE_SCHEMA = {
    "weighting_scheme": pl.Utf8,
    "year_start": pl.Int32,
    "year_end": pl.Int32,
    "n_regions": pl.Int32,
    "beta": pl.Float64,
    "intercept": pl.Float64,
    "correlation": pl.Float64,
    "r_squared": pl.Float64,
}

# Контракт moran_global: глобальная пространственная автокорреляция индекса по (year, scheme).
# morans_i — глобальный индекс Морана (>0 ⇒ соседние регионы похожи); expected_i = -1/(n-1) —
# ожидание при отсутствии автокорреляции; z_score/p_value — значимость перестановочным тестом
# (999 перестановок, seed=42). Веса — смежность по общей границе (rook), строкан-нормированные;
# n_regions — число регионов с соседями (эксклавы/острова исключены).
MORAN_GLOBAL_SCHEMA = {
    "weighting_scheme": pl.Utf8,
    "year": pl.Int32,
    "morans_i": pl.Float64,
    "expected_i": pl.Float64,
    "z_score": pl.Float64,
    "p_value": pl.Float64,
    "n_regions": pl.Int32,
}

# Контракт moran_local: локальная автокорреляция (LISA) по региону для (year, scheme). local_i —
# локальный индекс Морана; quadrant при p<0.05 — тип кластера: HH/LL (регион и соседи вместе
# высоко/низко), HL/LH (пространственные выбросы), иначе "ns". p_value — перестановочная значимость.
# Веса — те же rook-смежности. Регионы без соседей — quadrant "ns", p_value/local_i = null.
MORAN_LOCAL_SCHEMA = {
    "weighting_scheme": pl.Utf8,
    "year": pl.Int32,
    "okato": pl.Utf8,
    "local_i": pl.Float64,
    "quadrant": pl.Utf8,
    "p_value": pl.Float64,
    "n_neighbors": pl.Int32,
}

# Контракт index_dispersion: межрегиональный разброс КОМПОЗИТНОГО ИНДЕКСА по годам (σ-сходимость).
# Грань — (year, weighting_scheme). В отличие от dispersion (по метрикам), здесь — разброс самого
# индекса развития по регионам: сужается ли он во времени (σ-сходимость) и динамика неравенства.
# cv — коэффициент вариации (мера σ-сходимости), gini и p90_p10 — неравенство. Индекс z-нормирован,
# поэтому измеряет относительные позиции; меры разброса инвариантны к шкале и сопоставимы по годам.
INDEX_DISPERSION_SCHEMA = {
    "year": pl.Int32,
    "weighting_scheme": pl.Utf8,
    "n_regions": pl.Int32,
    "mean": pl.Float64,
    "std": pl.Float64,
    "cv": pl.Float64,
    "p10": pl.Float64,
    "p90": pl.Float64,
    "p90_p10": pl.Float64,
    "gini": pl.Float64,
}

# Контракт scheme_agreement: согласованность рейтингов между схемами весов по годам.
# Грань — (year, scheme_a, scheme_b), пары неупорядоченные (a<b). spearman — ранговая корреляция
# Спирмена между рейтингами двух схем за год (по совпадающим регионам). Близко к 1 ⇒ выбор схемы
# почти не меняет порядок; заметно ниже ⇒ рейтинг чувствителен к весам. Дополняет rank_robustness
# (там — по регионам; здесь — сводно по всему рейтингу и во времени).
SCHEME_AGREEMENT_SCHEMA = {
    "year": pl.Int32,
    "scheme_a": pl.Utf8,
    "scheme_b": pl.Utf8,
    "spearman": pl.Float64,
    "n_regions": pl.Int32,
}

# Контракт rank_robustness: чувствительность ранга региона к ВЫБОРУ схемы весов (в году).
# Грань — (okato, year). Ранг считается внутри (схема, год) по убыванию total_score (как в
# выдаче рейтинга), затем агрегируется по схемам: rank_best — лучшая позиция среди схем (min),
# rank_worst — худшая (max), rank_range = worst−best («коридор»). Большой коридор ⇒ место региона
# сильно зависит от произвольного выбора весов — научное ядро «прозрачного индекса».
RANK_ROBUSTNESS_SCHEMA = {
    "okato": pl.Utf8,
    "year": pl.Int32,
    "n_schemes": pl.Int32,
    "rank_best": pl.Int32,
    "rank_worst": pl.Int32,
    "rank_range": pl.Int32,
    "rank_mean": pl.Float64,
    "score_min": pl.Float64,
    "score_max": pl.Float64,
}

# Контракт correlations: парные корреляции метрик по регионам на год.
CORRELATIONS_SCHEMA = {
    "year": pl.Int32,
    "metric_a": pl.Int32,
    "metric_b": pl.Int32,
    "method": pl.Utf8,
    "correlation": pl.Float64,
    "n_regions": pl.Int32,
}

# Контракт index_decomposition: вклад доменов в годовое изменение индекса.
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

# Контракт data_quality: полнота/импутации аналитической сетки на (метрику, год).
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

# Контракт fact_region: типы + год в допустимом диапазоне. coerce приводит типы к схеме.
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
