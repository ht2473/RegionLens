"""Парные корреляции метрик по регионам (модуль «correlations»).

Производная описательная мера поверх features_wide: для каждого года считаем корреляцию между
парами метрик по регионам (метрики ядра, плотные значения). Метод — из конфига (spearman по
умолчанию: ранговый, устойчив к перекосам и выбросам региональных данных; либо pearson).

Это описание совместного движения показателей по регионам, а НЕ вывод о причинно-следственной
связи и НЕ прогноз: корреляция ≠ причинность. Никаких обучаемых моделей.

Spearman считается как Pearson по рангам (ties — средним рангом). Хранятся пары верхнего
треугольника (metric_a < metric_b), по одной на неупорядоченную пару. Параметры — из
config/analytics.yaml (correlations.method, correlations.min_regions); без хардкода.
"""

from dataclasses import dataclass

import numpy as np
import polars as pl
from scipy.stats import rankdata

from pipeline.config import load_config
from pipeline.contracts import CORRELATIONS_SCHEMA
from pipeline.duck import read_table, write_table
from pipeline.logging_setup import log

DEFAULT_DUCKDB_PATH = "data/regionlens.duckdb"

METHODS = ("spearman", "pearson")


@dataclass
class CorrelationsResult:
    """Итог модуля: таблица correlations (парные корреляции метрик на год)."""

    correlations: pl.DataFrame


def compute_correlations(
    features_wide: pl.DataFrame, *, method: str, min_regions: int
) -> pl.DataFrame:
    """Парные корреляции метрик по регионам для каждого года по контракту CORRELATIONS_SCHEMA.

    Для каждого года значения value_harmonized разворачиваются в матрицу регион×метрика;
    корреляция считается выбранным методом. Годы с числом регионов меньше min_regions
    пропускаются; пары с неопределённой корреляцией (нулевая дисперсия метрики) — тоже.
    """
    if method not in METHODS:
        raise ValueError(f"correlations.method должен быть из {METHODS}, получено: {method!r}")

    rows: list[dict[str, object]] = []
    for year in sorted(features_wide["year"].unique().to_list()):
        wide = (
            features_wide.filter(pl.col("year") == year)
            .pivot(on="metric_id", index="okato", values="value_harmonized")
            .drop("okato")
            .drop_nulls()
        )
        n_regions = wide.height
        if n_regions < min_regions or wide.width < 2:
            continue

        metric_ids = sorted(int(c) for c in wide.columns)
        arr = wide.select([str(m) for m in metric_ids]).to_numpy().astype(float)
        if method == "spearman":
            arr = np.apply_along_axis(
                rankdata, 0, arr
            )  # ранги по столбцам → Spearman через Pearson
        with np.errstate(invalid="ignore", divide="ignore"):
            corr = np.corrcoef(arr, rowvar=False)  # NaN для метрик без дисперсии — отсеются ниже

        for i in range(len(metric_ids)):
            for j in range(i + 1, len(metric_ids)):
                value = corr[i, j]
                if np.isnan(value):
                    continue  # метрика без дисперсии в этом году → корреляция не определена
                rows.append(
                    {
                        "year": year,
                        "metric_a": metric_ids[i],
                        "metric_b": metric_ids[j],
                        "method": method,
                        "correlation": float(value),
                        "n_regions": n_regions,
                    }
                )

    schema = dict(CORRELATIONS_SCHEMA)
    out = pl.DataFrame(rows, schema=schema) if rows else pl.DataFrame(schema=schema)
    return out.sort(["year", "metric_a", "metric_b"])


def run_correlations(
    features_wide: pl.DataFrame,
    *,
    duckdb_path: str = DEFAULT_DUCKDB_PATH,
    write: bool = True,
) -> CorrelationsResult:
    """Посчитать correlations и (при write=True) записать контрактную таблицу в DuckDB."""
    cfg = load_config("analytics").get("correlations") or {}
    method = str(cfg.get("method", "spearman"))
    min_regions = int(cfg.get("min_regions", 30))
    corr = compute_correlations(features_wide, method=method, min_regions=min_regions)
    log.info(
        "correlations_built",
        stage="correlations",
        rows=corr.height,
        years=corr["year"].n_unique(),
        method=method,
    )
    if write:
        write_table(duckdb_path, "correlations", corr)
    return CorrelationsResult(correlations=corr)


if __name__ == "__main__":
    fw = read_table(DEFAULT_DUCKDB_PATH, "features_wide")
    run_correlations(fw)
