"""Межрегиональный разброс индекса развития по годам — σ-сходимость (модуль «index_dispersion»).

Производная описательная мера поверх готового dev_index. В отличие от модуля dispersion (разброс
по отдельным метрикам), здесь мы смотрим на сам КОМПОЗИТНЫЙ ИНДЕКС: насколько регионы неравны по
уровню развития и сужается ли разрыв во времени (σ-сходимость). Для каждой (схема весов, год)
считаем меры разброса по регионам. Это НЕ модель и НЕ прогноз — только арифметика над уже
посчитанными баллами (стоп-правило Хартии соблюдено).

Индекс z-нормирован (баллы относительно окна), поэтому отражает ОТНОСИТЕЛЬНОЕ положение регионов;
меры разброса (cv, gini, p90/p10) инвариантны к шкале и сопоставимы между годами. Падение cv во
времени — признак σ-сходимости (регионы сближаются); рост — расхождения. Грань — (year, scheme).
"""

from dataclasses import dataclass

import numpy as np
import polars as pl

from pipeline.contracts import INDEX_DISPERSION_SCHEMA
from pipeline.duck import read_table, write_table
from pipeline.logging_setup import log

DEFAULT_DUCKDB_PATH = "data/regionlens.duckdb"
MIN_REGIONS = 5  # ниже этого меры разброса непоказательны


def _gini(values: np.ndarray) -> float:
    """Коэффициент Джини для неотрицательных значений (0 — равенство, выше — неравенство)."""
    x = np.sort(values)
    n = x.size
    total = x.sum()
    if n == 0 or total <= 0:
        return float("nan")
    # G = sum_i (2i - n - 1) x_i / (n * sum x), i = 1..n
    coef = 2.0 * np.arange(1, n + 1) - n - 1
    return float(coef.dot(x) / (n * total))


def compute_index_dispersion(dev_index: pl.DataFrame) -> pl.DataFrame:
    """Меры межрегионального разброса индекса по (схема весов, год). Контракт — INDEX_DISPERSION.

    Для каждой пары (weighting_scheme, year) берём баллы регионов и считаем mean/std/cv,
    перцентили p10/p90 и их отношение, коэффициент Джини. Предохранители: cv только при mean>0,
    p90/p10 только при p10>0, Джини только при положительной сумме; группы менее MIN_REGIONS
    регионов пропускаются.
    """
    keys = dev_index.select("weighting_scheme", "year").unique().sort(["weighting_scheme", "year"])
    rows: list[dict[str, object]] = []
    for key in keys.iter_rows(named=True):
        scheme, year = key["weighting_scheme"], key["year"]
        v = (
            dev_index.filter((pl.col("weighting_scheme") == scheme) & (pl.col("year") == year))[
                "total_score"
            ]
            .drop_nulls()
            .to_numpy()
        )
        if v.size < MIN_REGIONS:
            continue
        mean = float(v.mean())
        std = float(v.std())
        p10, p90 = (float(x) for x in np.percentile(v, [10, 90]))
        rows.append(
            {
                "year": int(year),
                "weighting_scheme": scheme,
                "n_regions": int(v.size),
                "mean": mean,
                "std": std,
                "cv": std / mean if mean > 0 else None,
                "p10": p10,
                "p90": p90,
                "p90_p10": p90 / p10 if p10 > 0 else None,
                "gini": _gini(v),
            }
        )

    df = (
        pl.DataFrame(rows, schema=INDEX_DISPERSION_SCHEMA)
        if rows
        else pl.DataFrame(schema=INDEX_DISPERSION_SCHEMA)
    )
    return df.with_columns(
        pl.when(pl.col("gini").is_nan()).then(None).otherwise(pl.col("gini")).alias("gini")
    ).sort(["weighting_scheme", "year"])


@dataclass
class IndexDispersionResult:
    """Итог модуля: таблица index_dispersion (разброс индекса по регионам на схему-год)."""

    index_dispersion: pl.DataFrame


def run_index_dispersion(
    dev_index: pl.DataFrame,
    *,
    duckdb_path: str = DEFAULT_DUCKDB_PATH,
    write: bool = True,
) -> IndexDispersionResult:
    """Посчитать index_dispersion и (при write=True) записать контрактную таблицу в DuckDB."""
    idp = compute_index_dispersion(dev_index)
    log.info(
        "index_dispersion_built",
        stage="index_dispersion",
        rows=idp.height,
        schemes=idp["weighting_scheme"].n_unique(),
        years=idp["year"].n_unique(),
    )
    if write:
        write_table(duckdb_path, "index_dispersion", idp)
    return IndexDispersionResult(index_dispersion=idp)


if __name__ == "__main__":
    dev = read_table(DEFAULT_DUCKDB_PATH, "dev_index")
    run_index_dispersion(dev)
