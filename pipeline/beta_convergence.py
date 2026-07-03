"""β-сходимость индекса развития (модуль «beta_convergence», поток B).

Производная описательная мера поверх готового dev_index, дополняющая σ-сходимость. β-сходимость
проверяет, догоняли ли изначально отстающие регионы: для каждой схемы весов берём стартовый и
конечный год окна и описательно регрессируем изменение индекса (рост за период) на стартовый
уровень по регионам. Отрицательный наклон (beta<0) — регионы с низким стартом росли быстрее.

Важная оговорка: индекс z-нормирован (баллы относительно окна), поэтому «рост» — это изменение
ОТНОСИТЕЛЬНОЙ позиции. β-сходимость здесь отражает мобильность / возврат к среднему, а не
абсолютное догоняние. Это НЕ модель и НЕ прогноз: наклон и корреляция — закрытая арифметика
(beta = cov(x,y)/var(x)) над уже посчитанными баллами; стоп-правило валидации соблюдено. Контраст
с σ-сходимостью (мобильность без сужения общего разброса) — содержательный результат сам по себе.
"""

from dataclasses import dataclass

import numpy as np
import polars as pl

from pipeline.contracts import BETA_CONVERGENCE_SCHEMA
from pipeline.duck import read_table, write_table
from pipeline.logging_setup import log

DEFAULT_DUCKDB_PATH = "data/regionlens.duckdb"
MIN_REGIONS = 5  # ниже этого регрессия непоказательна


def compute_beta_convergence(dev_index: pl.DataFrame) -> pl.DataFrame:
    """β-сходимость по схемам весов (грань weighting_scheme). Контракт BETA_CONVERGENCE_SCHEMA.

    Для каждой схемы: стартовый/конечный год — минимум и максимум года в dev_index. Берём баллы
    регионов в эти годы (по совпадающим регионам), рост = конечный − стартовый, и описательно
    регрессируем рост на стартовый уровень: beta (наклон), intercept, корреляция Пирсона и R².
    """
    schemes = sorted(dev_index["weighting_scheme"].unique().to_list())
    rows: list[dict[str, object]] = []
    for scheme in schemes:
        sub = dev_index.filter(pl.col("weighting_scheme") == scheme)
        y0 = int(sub["year"].min())  # type: ignore[arg-type]
        y1 = int(sub["year"].max())  # type: ignore[arg-type]
        if y0 == y1:
            continue
        start = sub.filter(pl.col("year") == y0).select(
            "okato", pl.col("total_score").alias("init")
        )
        end = sub.filter(pl.col("year") == y1).select("okato", pl.col("total_score").alias("fin"))
        merged = start.join(end, on="okato").drop_nulls()
        if merged.height < MIN_REGIONS:
            continue
        init = merged["init"].to_numpy()
        growth = merged["fin"].to_numpy() - init
        beta, intercept = (float(v) for v in np.polyfit(init, growth, 1))
        corr = float(np.corrcoef(init, growth)[0, 1]) if init.std() > 0 else float("nan")
        rows.append(
            {
                "weighting_scheme": scheme,
                "year_start": y0,
                "year_end": y1,
                "n_regions": merged.height,
                "beta": round(beta, 4),
                "intercept": round(intercept, 4),
                "correlation": None if np.isnan(corr) else round(corr, 4),
                "r_squared": None if np.isnan(corr) else round(corr * corr, 4),
            }
        )

    df = (
        pl.DataFrame(rows, schema=BETA_CONVERGENCE_SCHEMA)
        if rows
        else pl.DataFrame(schema=BETA_CONVERGENCE_SCHEMA)
    )
    return df.sort("weighting_scheme")


@dataclass
class BetaConvergenceResult:
    """Итог модуля: таблица beta_convergence (β-сходимость по схемам весов)."""

    beta_convergence: pl.DataFrame


def run_beta_convergence(
    dev_index: pl.DataFrame,
    *,
    duckdb_path: str = DEFAULT_DUCKDB_PATH,
    write: bool = True,
) -> BetaConvergenceResult:
    """Посчитать beta_convergence и (при write=True) записать контрактную таблицу в DuckDB."""
    bc = compute_beta_convergence(dev_index)
    log.info(
        "beta_convergence_built",
        stage="beta_convergence",
        rows=bc.height,
        betas={r["weighting_scheme"]: r["beta"] for r in bc.to_dicts()},
    )
    if write:
        write_table(duckdb_path, "beta_convergence", bc)
    return BetaConvergenceResult(beta_convergence=bc)


if __name__ == "__main__":
    dev = read_table(DEFAULT_DUCKDB_PATH, "dev_index")
    run_beta_convergence(dev)
