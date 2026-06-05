"""Признаки (Ф2 / S3): гармонизация форм, обогащение metric_dim, покрытие, ядро.

Блок A: из fact_region получаем сопоставимые значения (value_harmonized),
обогащаем справочник метрик (domain / value_type / higher_is_better / coverage)
и отбираем курируемое ядро. Блок B (далее) добавит pivot + импутацию + z-score
и запишет features_wide в DuckDB.

Параметры — из конфигов (без хардкода): окно и порог покрытия — analytics.yaml;
домены, ядро, метрика населения — indicators.yaml; правила value_type — value_types.yaml.
"""

from dataclasses import dataclass
from typing import Any

import polars as pl

from pipeline.config import load_config
from pipeline.logging_setup import log

# Правила value_type: (список правил подстрока->тип, тип по умолчанию, маркер «нет данных»).
ValueTypeRules = tuple[list[dict[str, str]], str, str | None]

# Только value_type=absolute делится на население; остальные формы уже сопоставимы.
ABSOLUTE = "absolute"


@dataclass
class CoreFeatures:
    """Промежуточный результат блока A — вход для блока B (pivot/импутация/z-score)."""

    metric_dim: pl.DataFrame  # обогащённый справочник (domain/value_type/higher_is_better/coverage)
    fact_core: pl.DataFrame  # окно + только ядро, с колонкой value_harmonized
    core_ids: list[int]  # metric_id метрик ядра
    window: list[int]  # годы окна анализа (2010..2024)


def classify_value_type(
    unit: str | None, rules: list[dict[str, str]], default: str, nodata_marker: str | None
) -> str:
    """Грубо определить value_type по строке unit (первое совпадение по подстроке).

    Это запасной классификатор для ХВОСТА (не-ядра): для метрик ядра value_type
    задан вручную в indicators.yaml и переопределяет результат этой функции.
    Маркер «нет данных» (ND) трактуем как default — исключение метрики решается
    доменом (excluded), а не типом значения.
    """
    u = unit or ""
    if nodata_marker and u.strip() == nodata_marker:
        return default
    ul = u.lower()
    for rule in rules:
        if rule["match"].lower() in ul:
            return rule["type"]
    return default


def compute_coverage(
    fact_region: pl.DataFrame, region_dim: pl.DataFrame, window: list[int]
) -> pl.DataFrame:
    """Покрытие метрики в окне: доля заполненных region-years по включённым регионам.

    Знаменатель = число включённых регионов (included_flag) × длина окна. Считаем
    только непустые значения (после М0 заглушки уже занулены). Возвращает (metric_id, coverage).
    """
    included = region_dim.filter(pl.col("included_flag")).select("okato")
    denom = included.height * len(window)
    if denom == 0:
        raise ValueError(
            "Знаменатель покрытия равен нулю (нет включённых регионов или пустое окно)."
        )
    return (
        fact_region.filter(pl.col("year").is_in(window))
        .join(included, on="okato", how="inner")
        .filter(pl.col("value").is_not_null())
        .group_by("metric_id")
        .agg(pl.struct(["okato", "year"]).n_unique().alias("cells"))
        .with_columns((pl.col("cells") / denom).alias("coverage"))
        .select(["metric_id", "coverage"])
    )


def enrich_metric_dim(
    metric_dim: pl.DataFrame,
    indicators_cfg: dict[str, Any],
    vt_rules: ValueTypeRules,
    coverage: pl.DataFrame,
) -> pl.DataFrame:
    """Дополнить metric_dim полями domain / value_type / higher_is_better / coverage.

    Для метрик ядра все три поля берутся из indicators.yaml (core) — это приоритет.
    Для остальных: domain — по карте section→домен (иначе default_domain); value_type —
    по правилам из value_types.yaml; higher_is_better — null (направление задано лишь у ядра).
    """
    domains_map = indicators_cfg.get("domains") or {}
    default_domain = str(indicators_cfg.get("default_domain", "excluded"))
    core = {int(c["metric_id"]): c for c in (indicators_cfg.get("core") or [])}
    rules, default_vt, nodata = vt_rules

    domain_out: list[str] = []
    vt_out: list[str] = []
    hib_out: list[bool | None] = []
    for row in metric_dim.to_dicts():
        mid = int(row["metric_id"])
        if mid in core:
            spec = core[mid]
            domain_out.append(str(spec["domain"]))
            vt_out.append(str(spec["value_type"]))
            hib_out.append(bool(spec["higher_is_better"]))
        else:
            domain_out.append(str(domains_map.get(row["section"], default_domain)))
            vt_out.append(classify_value_type(row["unit"], rules, default_vt, nodata))
            hib_out.append(None)

    enriched = metric_dim.with_columns(
        pl.Series("domain", domain_out, dtype=pl.Utf8),
        pl.Series("value_type", vt_out, dtype=pl.Utf8),
        pl.Series("higher_is_better", hib_out, dtype=pl.Boolean),
    )
    return enriched.join(coverage, on="metric_id", how="left").with_columns(
        pl.col("coverage").fill_null(0.0)
    )


def harmonize(fact: pl.DataFrame, metric_dim: pl.DataFrame, pop_id: int) -> pl.DataFrame:
    """Привести значения к сопоставимой форме → колонка value_harmonized.

    value_type=absolute делится на среднегодовую численность населения (metric_id=pop_id);
    per_capita / share / index / rate_yoy уже сопоставимы и проходят без изменений.
    Если население отсутствует или ≤0 — результат null (импутация разберётся позже).
    """
    pop = fact.filter(pl.col("metric_id") == pop_id).select(
        ["okato", "year", pl.col("value").alias("pop")]
    )
    joined = fact.join(
        metric_dim.select(["metric_id", "value_type"]), on="metric_id", how="left"
    ).join(pop, on=["okato", "year"], how="left")
    per_capita = pl.when(pl.col("pop") > 0).then(pl.col("value") / pl.col("pop")).otherwise(None)
    return joined.with_columns(
        pl.when(pl.col("value_type") == ABSOLUTE)
        .then(per_capita)
        .otherwise(pl.col("value"))
        .alias("value_harmonized")
    )


def select_core(
    metric_dim: pl.DataFrame, indicators_cfg: dict[str, Any], coverage_threshold: float
) -> list[int]:
    """Список metric_id ядра (из indicators.core). Метрики с покрытием ниже порога логируются.

    Ядро курируется вручную (отобрано на чистых данных), поэтому здесь не отсеиваем,
    а лишь предупреждаем, если какая-то метрика просела по покрытию ниже порога.
    """
    core_ids = [int(c["metric_id"]) for c in (indicators_cfg.get("core") or [])]
    cov = dict(
        zip(
            metric_dim["metric_id"].to_list(),
            metric_dim["coverage"].to_list(),
            strict=True,
        )
    )
    low = [(mid, cov.get(mid)) for mid in core_ids if (cov.get(mid) or 0.0) < coverage_threshold]
    if low:
        log.warning(
            "core_below_coverage", stage="features", threshold=coverage_threshold, items=low
        )
    log.info("core_selected", stage="features", n_core=len(core_ids))
    return core_ids


def prepare_features(
    metric_dim: pl.DataFrame, region_dim: pl.DataFrame, fact_region: pl.DataFrame
) -> CoreFeatures:
    """Блок A целиком: покрытие → обогащение metric_dim → гармонизация → отбор ядра.

    Конфиги читаются из config/*.yaml. Возвращает CoreFeatures (обогащённый справочник,
    факт ядра с value_harmonized в окне, список core_ids, годы окна) — вход для блока B.
    """
    indicators = load_config("indicators")
    value_types = load_config("value_types")
    analytics = load_config("analytics")

    win = analytics["window"]
    window = list(range(int(win["start"]), int(win["end"]) + 1))
    pop_id = int(indicators["population_metric_id"])
    rules: ValueTypeRules = (
        list(value_types.get("rules") or []),
        str(value_types.get("default", ABSOLUTE)),
        value_types.get("nodata_marker"),
    )

    coverage = compute_coverage(fact_region, region_dim, window)
    enriched = enrich_metric_dim(metric_dim, indicators, rules, coverage)
    core_ids = select_core(enriched, indicators, float(analytics["coverage_threshold"]))

    fact_win = fact_region.filter(pl.col("year").is_in(window))
    fact_core = (
        harmonize(fact_win, enriched, pop_id)
        .filter(pl.col("metric_id").is_in(core_ids))
        .select(["okato", "metric_id", "year", "value", "value_harmonized"])
    )
    log.info(
        "features_prepared",
        stage="features",
        window=f"{window[0]}-{window[-1]}",
        core_rows=fact_core.height,
        metrics_enriched=enriched.height,
    )
    return CoreFeatures(metric_dim=enriched, fact_core=fact_core, core_ids=core_ids, window=window)
