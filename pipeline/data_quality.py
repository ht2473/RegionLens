"""Качество данных аналитической сетки (модуль «data_quality»).

Производная описательная мера поверх готовой сетки ядра (features_wide) и сырья (fact_region):
по каждой паре (метрика, год) считаем, насколько полна и насколько достроена аналитическая
матрица. Это НЕ модель и НЕ прогноз — только подсчёт ячеек.

Две полноты намеренно разведены (для absolute-метрик они расходятся):
- **Сырьё** (`n_present_raw` / `completeness_raw`): доля ячеек сетки с непустым СЫРЫМ значением
  Росстата — доступность источника, считается ДО гармонизации. Оконный роллап
  `Σn_present_raw / Σn_regions` по метрике в точности совпадает с `metric_dim.coverage`.
- **Импутации** (`n_imputed` / `impute_share`): доля ячеек ГАРМОНИЗИРОВАННОЙ сетки, которые
  пришлось достроить. Для absolute-метрик ячейка может быть импутирована, хотя сырьё было:
  при гармонизации absolute делится на население, и если численность за (регион, год) отсутствует,
  гармонизированное значение пустеет. Поэтому `completeness_raw ≥ 1 − impute_share`, с равенством
  для величин без деления на население (share/per_capita/index/rate_yoy).

Грань таблицы — (metric_id, year) по ядру. Имя/домен/тип метрики и оконное `coverage`
подтягиваются на уровне запроса из `metric_dim` (как в dispersion) — здесь не дублируются.
Параметров-порогов у модуля нет (чистый подсчёт), поэтому в config/*.yaml ничего не вводится.
"""

from dataclasses import dataclass

import polars as pl

from pipeline.contracts import DATA_QUALITY_SCHEMA
from pipeline.duck import read_table, write_table
from pipeline.logging_setup import log

DEFAULT_DUCKDB_PATH = "data/regionlens.duckdb"


@dataclass
class DataQualityResult:
    """Итог модуля: таблица data_quality (полнота/импутации сетки на метрику-год)."""

    data_quality: pl.DataFrame


def compute_data_quality(features_wide: pl.DataFrame, fact_region: pl.DataFrame) -> pl.DataFrame:
    """Полнота и доля импутаций аналитической сетки для каждой пары (метрика, год).

    Возвращает DataFrame по контракту DATA_QUALITY_SCHEMA. n_regions — число ячеек сетки ядра
    в группе (включённые регионы); n_present_raw — из них с непустым сырым значением (left join
    к fact_region по точной грани); n_imputed — достроенные ячейки гармонизированной сетки.
    Производные доли completeness_raw и impute_share — относительно n_regions.
    """
    # Приводим ключи соединения к общему типу (features_wide и fact_region читаются из DuckDB
    # независимо; year может быть Int64/Int32 в синтетике тестов) — иначе join по разным типам.
    fw = features_wide.with_columns(
        pl.col("year").cast(pl.Int64), pl.col("metric_id").cast(pl.Int32)
    )
    fr = fact_region.select("okato", "year", "metric_id", "value").with_columns(
        pl.col("year").cast(pl.Int64), pl.col("metric_id").cast(pl.Int32)
    )

    grid = fw.group_by(["metric_id", "year"]).agg(
        pl.len().alias("n_regions"),
        pl.col("is_imputed").sum().alias("_n_imputed"),
    )
    # Сырая полнота: ячейки сетки ← непустое сырьё (fact_region уникален по грани, дублей нет).
    keys = fw.select("okato", "year", "metric_id").unique()
    raw = (
        keys.join(fr, on=["okato", "year", "metric_id"], how="left")
        .group_by(["metric_id", "year"])
        .agg(pl.col("value").is_not_null().sum().alias("_n_present_raw"))
    )

    out = (
        grid.join(raw, on=["metric_id", "year"], how="left")
        .with_columns(
            pl.col("n_regions").cast(pl.Int32),
            pl.col("_n_present_raw").cast(pl.Int32).alias("n_present_raw"),
            pl.col("_n_imputed").cast(pl.Int32).alias("n_imputed"),
        )
        .with_columns(
            (pl.col("n_present_raw") / pl.col("n_regions")).alias("completeness_raw"),
            (pl.col("n_imputed") / pl.col("n_regions")).alias("impute_share"),
            pl.col("year").cast(pl.Int32),
        )
    )
    return out.select(list(DATA_QUALITY_SCHEMA)).sort(["metric_id", "year"])


def run_data_quality(
    features_wide: pl.DataFrame,
    fact_region: pl.DataFrame,
    *,
    duckdb_path: str = DEFAULT_DUCKDB_PATH,
    write: bool = True,
) -> DataQualityResult:
    """Посчитать data_quality и (при write=True) записать контрактную таблицу в DuckDB."""
    dq = compute_data_quality(features_wide, fact_region)
    log.info(
        "data_quality_built",
        stage="data_quality",
        rows=dq.height,
        metrics=dq["metric_id"].n_unique(),
        years=dq["year"].n_unique(),
        imputed_cells=int(dq["n_imputed"].sum()),
    )
    if write:
        write_table(duckdb_path, "data_quality", dq)
    return DataQualityResult(data_quality=dq)


if __name__ == "__main__":
    fw = read_table(DEFAULT_DUCKDB_PATH, "features_wide")
    fr = read_table(DEFAULT_DUCKDB_PATH, "fact_region")
    run_data_quality(fw, fr)
