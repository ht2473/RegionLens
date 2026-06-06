"""Признаки (Ф2 / S3): гармонизация форм, обогащение metric_dim, покрытие, ядро,
импутация и z-score → запись features_wide в DuckDB.

Блок A: из fact_region получаем сопоставимые значения (value_harmonized),
обогащаем справочник метрик (domain / value_type / higher_is_better / coverage)
и отбираем курируемое ядро.
Блок B: pivot ядра в полную сетку (включённые регионы × годы окна × метрики ядра),
импутация с предохранителями (+ is_imputed), z-score по году, запись в DuckDB.

Параметры — из конфигов (без хардкода): окно, пороги покрытия и импутации — analytics.yaml;
домены, ядро, метрика населения — indicators.yaml; правила value_type — value_types.yaml.
"""

from dataclasses import dataclass
from typing import Any

import polars as pl

from pipeline.config import load_config
from pipeline.duck import write_table
from pipeline.logging_setup import log

# Правила value_type: (список правил подстрока->тип, тип по умолчанию, маркер «нет данных»).
ValueTypeRules = tuple[list[dict[str, str]], str, str | None]

# Только value_type=absolute делится на население; остальные формы уже сопоставимы.
ABSOLUTE = "absolute"

# Путь к аналитическому хранилищу по умолчанию (как в pipeline.etl.DEFAULT_DUCKDB_PATH).
DEFAULT_DUCKDB_PATH = "data/regionlens.duckdb"


@dataclass
class CoreFeatures:
    """Промежуточный результат блока A — вход для блока B (pivot/импутация/z-score)."""

    metric_dim: pl.DataFrame  # обогащённый справочник (domain/value_type/higher_is_better/coverage)
    fact_core: pl.DataFrame  # окно + только ядро, с колонкой value_harmonized
    core_ids: list[int]  # metric_id метрик ядра
    window: list[int]  # годы окна анализа (2010..2024)


@dataclass
class FeaturesResult:
    """Итог Ф2: матрица признаков и обогащённый справочник метрик."""

    features_wide: pl.DataFrame
    metric_dim: pl.DataFrame


# --------------------------------------------------------------------------- #
# Блок A: гармонизация форм, обогащение metric_dim, покрытие, отбор ядра
# --------------------------------------------------------------------------- #
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


# --------------------------------------------------------------------------- #
# Блок B: pivot ядра, импутация с предохранителями, z-score, запись
# --------------------------------------------------------------------------- #
def build_long_grid(
    fact_core: pl.DataFrame, region_dim: pl.DataFrame, core_ids: list[int], window: list[int]
) -> pl.DataFrame:
    """Полная длинная сетка: включённые регионы × годы окна × метрики ядра.

    Декартово произведение даёт прямоугольную матрицу (пропуски явные — null),
    к которой слева подклеиваются гармонизированные значения. Только included_flag-регионы
    (дубль-варианты «с/без АО» не задваиваются, когда included_flag проставлен верно).
    """
    included = region_dim.filter(pl.col("included_flag")).select("okato")
    years = pl.DataFrame({"year": pl.Series(window, dtype=pl.Int64)})
    metrics = pl.DataFrame({"metric_id": pl.Series(core_ids, dtype=pl.Int32)})
    grid = included.join(years, how="cross").join(metrics, how="cross")
    return grid.join(
        fact_core.select(["okato", "year", "metric_id", "value_harmonized"]),
        on=["okato", "year", "metric_id"],
        how="left",
    )


def impute_features(grid: pl.DataFrame, max_gap: int, share_max: float) -> pl.DataFrame:
    """Импутация с предохранителями.

    Возвращает (okato, year, metric_id, value_harmonized, is_imputed).

    Шаги: (1) линейная интерполяция внутри региона по времени, но только короткие внутренние
    разрывы (длина серии пропусков ≤ max_gap); (2) остаток — медиана по (metric_id, year) между
    регионами; (3) предохранитель: если что-то ещё пусто — медиана по метрике.
    Падаем, если доля импутаций превысила порог impute_share_max или остались пропуски.
    """
    g = grid.sort(["okato", "metric_id", "year"]).with_columns(
        pl.col("value_harmonized").is_null().alias("_isnull"),
        pl.col("value_harmonized")
        .is_not_null()
        .cast(pl.Int32)
        .cum_sum()
        .over(["okato", "metric_id"])
        .alias("_anchor"),
        pl.col("value_harmonized").interpolate().over(["okato", "metric_id"]).alias("_interp"),
    )
    # длина серии пропусков, относящейся к одному «якорю» (последнему непустому)
    g = g.with_columns(
        pl.col("_isnull").sum().over(["okato", "metric_id", "_anchor"]).alias("_gap")
    )
    # шаг 1: короткие внутренние разрывы заполняем интерполяцией (края interpolate не трогает)
    g = g.with_columns(
        pl.when(pl.col("value_harmonized").is_not_null())
        .then(pl.col("value_harmonized"))
        .when(pl.col("_interp").is_not_null() & (pl.col("_gap") <= max_gap))
        .then(pl.col("_interp"))
        .otherwise(None)
        .alias("_vh1")
    )
    # шаг 2: межрегиональная медиана по (metric_id, year)
    g = g.with_columns(pl.col("_vh1").median().over(["metric_id", "year"]).alias("_med_my"))
    g = g.with_columns(
        pl.when(pl.col("_vh1").is_not_null())
        .then(pl.col("_vh1"))
        .otherwise(pl.col("_med_my"))
        .alias("_vh2")
    )
    # шаг 3 (предохранитель): остаток — медиана по всей метрике
    g = g.with_columns(pl.col("_vh2").median().over(["metric_id"]).alias("_med_m"))
    g = g.with_columns(
        pl.when(pl.col("_vh2").is_not_null())
        .then(pl.col("_vh2"))
        .otherwise(pl.col("_med_m"))
        .alias("_vh")
    )
    g = g.with_columns((pl.col("_isnull") & pl.col("_vh").is_not_null()).alias("is_imputed"))

    n_cells = g.height
    n_imp = int(g["is_imputed"].sum())
    share = n_imp / n_cells if n_cells else 0.0
    if share > share_max:
        raise ValueError(
            f"Доля импутаций {share:.3f} превышает порог impute_share_max={share_max}."
        )
    still_null = int(g["_vh"].is_null().sum())
    if still_null:
        raise ValueError(f"После импутации осталось {still_null} пустых ячеек ядра.")
    log.info(
        "features_imputed",
        stage="features",
        cells=n_cells,
        imputed=n_imp,
        impute_share=round(share, 4),
    )
    return g.select(
        "okato",
        "year",
        "metric_id",
        pl.col("_vh").alias("value_harmonized"),
        "is_imputed",
    )


def add_zscore(features: pl.DataFrame) -> pl.DataFrame:
    """Добавить z_value: стандартизация value_harmonized по (metric_id, year).

    z = (x - среднее) / стандартное отклонение в пределах года. Если std не определён
    или равен нулю (вырожденный случай) — z=0. Направление (higher_is_better) здесь
    НЕ применяется: знак учитывается на этапе индекса (Ф4), контракт хранит «сырой» z.
    """
    mean = pl.col("value_harmonized").mean().over(["metric_id", "year"])
    std = pl.col("value_harmonized").std().over(["metric_id", "year"])
    return features.with_columns(
        pl.when(std.is_not_null() & (std > 0))
        .then((pl.col("value_harmonized") - mean) / std)
        .otherwise(0.0)
        .alias("z_value")
    )


def build_features_wide(core: CoreFeatures, region_dim: pl.DataFrame) -> pl.DataFrame:
    """Собрать features_wide: сетка → импутация → z-score (пороги — из analytics.yaml)."""
    analytics = load_config("analytics")
    max_gap = int(analytics["impute_max_gap"])
    share_max = float(analytics["impute_share_max"])

    grid = build_long_grid(core.fact_core, region_dim, core.core_ids, core.window)
    imputed = impute_features(grid, max_gap, share_max)
    return (
        add_zscore(imputed)
        .select(["okato", "year", "metric_id", "value_harmonized", "z_value", "is_imputed"])
        .sort(["okato", "metric_id", "year"])
    )


def run_features(
    metric_dim: pl.DataFrame,
    region_dim: pl.DataFrame,
    fact_region: pl.DataFrame,
    *,
    duckdb_path: str = DEFAULT_DUCKDB_PATH,
    write: bool = True,
) -> FeaturesResult:
    """Ф2 целиком: блок A → блок B. При write=True пишет features_wide и обогащённый metric_dim."""
    core = prepare_features(metric_dim, region_dim, fact_region)
    features_wide = build_features_wide(core, region_dim)
    if write:
        write_table(duckdb_path, "features_wide", features_wide)
        # обогащённый metric_dim перезаписывает базовый из Ф1 (добавлены domain/value_type/...)
        write_table(duckdb_path, "metric_dim", core.metric_dim)
        log.info(
            "features_written",
            stage="features",
            path=duckdb_path,
            features_rows=features_wide.height,
            metric_dim_rows=core.metric_dim.height,
        )
    return FeaturesResult(features_wide=features_wide, metric_dim=core.metric_dim)


if __name__ == "__main__":
    from pipeline.etl import run_etl

    etl = run_etl(write=False)
    run_features(etl.metric_dim, etl.region_dim, etl.fact_region)
