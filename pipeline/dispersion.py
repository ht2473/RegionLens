"""Межрегиональный разброс/неравенство показателей (модуль «dispersion»).

Производная описательная мера поверх готовых value_harmonized из features_wide: по каждой
паре (метрика, год) считаем статистики разброса значений по регионам — насколько регионы
неравны по показателю и (через ряд лет) расширяется ли разрыв. Это НЕ обучаемая модель,
НЕ прогноз и НЕ причинность — стоп-правило «нет новых аналитических моделей» не нарушается
(только арифметика над уже посчитанными значениями).

Шкала имеет значение. Коэффициент вариации (cv) и отношение P90/P10 осмысленны лишь для
величин со шкалой отношений (есть содержательный ноль): per_capita, absolute (после гармонизации —
подушевое), share. Для index/rate_yoy (произвольная точка отсчёта) эти отношения вводят в
заблуждение и остаются NULL. Дополнительные предохранители: cv только при mean>0, P90/P10
только при p10>0. Разброс, не зависящий от шкалы (std, iqr, value_range), считается всегда.

Параметр min_regions — из config/analytics.yaml (dispersion.min_regions); без хардкода.
"""

from dataclasses import dataclass

import polars as pl

from pipeline.config import load_config
from pipeline.contracts import DISPERSION_SCHEMA
from pipeline.duck import read_table, write_table
from pipeline.logging_setup import log

DEFAULT_DUCKDB_PATH = "data/regionlens.duckdb"

# value_type со шкалой отношений (содержательный ноль) — для них cv и P90/P10 интерпретируемы.
RATIO_SCALE_TYPES = ("absolute", "per_capita", "share")


@dataclass
class DispersionResult:
    """Итог модуля: таблица dispersion (разброс по регионам на метрику-год)."""

    dispersion: pl.DataFrame


def compute_dispersion(
    features_wide: pl.DataFrame, metric_dim: pl.DataFrame, *, min_regions: int
) -> pl.DataFrame:
    """Статистики разброса value_harmonized по регионам для каждой пары (метрика, год).

    Возвращает DataFrame по контракту DISPERSION_SCHEMA. Группы, где регионов меньше
    min_regions, отбрасываются (разброс на крошечной выборке непоказателен). cv и
    p90_p10_ratio заполняются только для метрик со шкалой отношений и при положительных
    mean/p10 соответственно, иначе NULL.
    """
    ratio = metric_dim.select(
        "metric_id",
        pl.col("value_type").is_in(RATIO_SCALE_TYPES).alias("_is_ratio"),
    )
    agg = (
        features_wide.group_by(["metric_id", "year"])
        .agg(
            pl.col("value_harmonized").count().alias("n_regions"),
            pl.col("value_harmonized").mean().alias("mean"),
            pl.col("value_harmonized").median().alias("median"),
            pl.col("value_harmonized").std().alias("std"),
            pl.col("value_harmonized").quantile(0.10, interpolation="linear").alias("p10"),
            pl.col("value_harmonized").quantile(0.90, interpolation="linear").alias("p90"),
            pl.col("value_harmonized").quantile(0.25, interpolation="linear").alias("_p25"),
            pl.col("value_harmonized").quantile(0.75, interpolation="linear").alias("_p75"),
            pl.col("value_harmonized").min().alias("_min"),
            pl.col("value_harmonized").max().alias("_max"),
        )
        .filter(pl.col("n_regions") >= min_regions)
        .join(ratio, on="metric_id", how="left")
    )
    derived = agg.with_columns(
        (pl.col("_p75") - pl.col("_p25")).alias("iqr"),
        (pl.col("_max") - pl.col("_min")).alias("value_range"),
        pl.when(pl.col("_is_ratio") & (pl.col("mean") > 0))
        .then(pl.col("std") / pl.col("mean"))
        .otherwise(None)
        .alias("cv"),
        pl.when(pl.col("_is_ratio") & (pl.col("p10") > 0))
        .then(pl.col("p90") / pl.col("p10"))
        .otherwise(None)
        .alias("p90_p10_ratio"),
    )
    return (
        derived.select(list(DISPERSION_SCHEMA))
        .with_columns(
            pl.col("metric_id").cast(pl.Int32),
            pl.col("year").cast(pl.Int32),
            pl.col("n_regions").cast(pl.Int32),
        )
        .sort(["metric_id", "year"])
    )


def run_dispersion(
    features_wide: pl.DataFrame,
    metric_dim: pl.DataFrame,
    *,
    duckdb_path: str = DEFAULT_DUCKDB_PATH,
    write: bool = True,
) -> DispersionResult:
    """Посчитать dispersion и (при write=True) записать контрактную таблицу в DuckDB."""
    cfg = load_config("analytics").get("dispersion") or {}
    min_regions = int(cfg.get("min_regions", 5))
    disp = compute_dispersion(features_wide, metric_dim, min_regions=min_regions)
    log.info(
        "dispersion_built",
        stage="dispersion",
        rows=disp.height,
        metrics=disp["metric_id"].n_unique(),
        years=disp["year"].n_unique(),
    )
    if write:
        write_table(duckdb_path, "dispersion", disp)
    return DispersionResult(dispersion=disp)


if __name__ == "__main__":
    fw = read_table(DEFAULT_DUCKDB_PATH, "features_wide")
    md = read_table(DEFAULT_DUCKDB_PATH, "metric_dim")
    run_dispersion(fw, md)
