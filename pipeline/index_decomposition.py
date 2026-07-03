"""Декомпозиция изменения индекса развития по доменам (модуль «index_decomposition»).

Отвечает на описательный вопрос: за счёт каких доменов изменился композитный индекс региона
от года к году. Это разложение уже посчитанного индекса, а НЕ модель и НЕ прогноз.

Индекс собирается как `total_score = to_100(Σ_d w_d · dscore_d)`, где `to_100` — аффинная
нормировка в [0;100] единым по окну преобразованием (a·x + b). Поэтому годовое изменение
раскладывается ТОЧНО:

    Δtotal = a · Σ_d w_d · Δdscore_d,   вклад домена d = a · w_d · Δdscore_d.

Считаем вклад пропорциональным распределением фактического Δtotal по взвешенным изменениям
доменов: `contribution_d = Δtotal · (w_d·Δdscore_d) / Σ_k(w_k·Δdscore_k)`. Масштаб a при этом
сокращается, а сумма вкладов по доменам в точности равна Δtotal_score (свойство проверяется
тестом). Если знаменатель ≈ 0 (индекс почти не изменился) — вклады нулевые.

Для согласованности с dev_index переиспользуются его функции compute_domain_scores,
scheme_weights и to_100 (те же доменные баллы, те же веса equal/pca/expert).
"""

from dataclasses import dataclass

import numpy as np
import polars as pl

from pipeline.config import load_config
from pipeline.contracts import INDEX_DECOMPOSITION_SCHEMA
from pipeline.dev_index import compute_domain_scores, scheme_weights, to_100
from pipeline.duck import read_table, write_table
from pipeline.logging_setup import log

DEFAULT_DUCKDB_PATH = "data/regionlens.duckdb"

# Порог знаменателя пропорции: ниже него считаем, что индекс не менялся (вклады = 0).
DENOM_EPS = 1e-9


@dataclass
class IndexDecompositionResult:
    """Итог модуля: таблица index_decomposition (вклад доменов в Δиндекса)."""

    index_decomposition: pl.DataFrame


def decompose_for_weights(
    scored: pl.DataFrame,
    domains: list[str],
    scheme: str,
    weights: np.ndarray,
    *,
    eps: float = DENOM_EPS,
) -> pl.DataFrame:
    """Вклад доменов в годовое изменение индекса для одной схемы и заданных весов.

    scored: okato, year, <домены> (dscore) и total_score (итог по этой схеме). Возвращает
    длинные строки по контракту: на (регион, год, домен) — Δиндекса, Δdscore домена, его вес и
    вклад. Берутся только пары соседних лет (year − предыдущий = 1); вклады в сумме по доменам
    дают delta_total_score.
    """
    wmap = {d: float(weights[i]) for i, d in enumerate(domains)}
    sdf = (
        scored.sort(["okato", "year"])
        .with_columns(
            pl.col("year").diff().over("okato").alias("_gap"),
            pl.col("total_score").diff().over("okato").alias("delta_total"),
            *[pl.col(d).diff().over("okato").alias(f"_dd_{d}") for d in domains],
        )
        .with_columns(*[(pl.col(f"_dd_{d}") * wmap[d]).alias(f"_wc_{d}") for d in domains])
        .with_columns(pl.sum_horizontal([f"_wc_{d}" for d in domains]).alias("_denom"))
        .filter((pl.col("_gap") == 1) & pl.col("delta_total").is_not_null())
    )

    parts: list[pl.DataFrame] = []
    for d in domains:
        contribution = (
            pl.when(pl.col("_denom").abs() < eps)
            .then(pl.lit(0.0))
            .otherwise(pl.col("delta_total") * pl.col(f"_wc_{d}") / pl.col("_denom"))
        )
        parts.append(
            sdf.select(
                pl.col("okato"),
                pl.col("year").cast(pl.Int32),
                pl.lit(scheme).alias("weighting_scheme"),
                pl.lit(d).alias("domain"),
                pl.col("delta_total").alias("delta_total_score"),
                pl.col(f"_dd_{d}").alias("domain_delta"),
                pl.lit(wmap[d]).alias("weight"),
                contribution.alias("contribution"),
            )
        )
    if not parts:
        return pl.DataFrame(schema=dict(INDEX_DECOMPOSITION_SCHEMA))
    return pl.concat(parts)


def compute_index_decomposition(
    features_wide: pl.DataFrame, metric_dim: pl.DataFrame, *, eps: float = DENOM_EPS
) -> pl.DataFrame:
    """Декомпозиция Δиндекса по доменам для всех схем весов (по контракту схемы).

    Переиспользует функции dev_index, поэтому доменные баллы, веса и итог совпадают с индексом
    бит-в-бит. Результат отсортирован по (схема, регион, год, домен).
    """
    weights_cfg = load_config("weights")
    schemes = list((weights_cfg.get("schemes") or {}).keys())
    expert = (weights_cfg.get("schemes") or {}).get("expert") or {}

    wide = compute_domain_scores(features_wide, metric_dim)
    domains = [c for c in wide.columns if c not in ("okato", "year")]
    domain_matrix = wide.select(domains).to_numpy()

    parts: list[pl.DataFrame] = []
    for scheme in schemes:
        weights = scheme_weights(domain_matrix, domains, scheme, expert)
        total = to_100(domain_matrix @ weights)
        scored = wide.with_columns(pl.Series("total_score", total))
        parts.append(decompose_for_weights(scored, domains, scheme, weights, eps=eps))

    out = pl.concat(parts) if parts else pl.DataFrame(schema=dict(INDEX_DECOMPOSITION_SCHEMA))
    return (
        out.select(list(INDEX_DECOMPOSITION_SCHEMA))
        .with_columns(pl.col("year").cast(pl.Int32))
        .sort(["weighting_scheme", "okato", "year", "domain"])
    )


def run_index_decomposition(
    features_wide: pl.DataFrame,
    metric_dim: pl.DataFrame,
    *,
    duckdb_path: str = DEFAULT_DUCKDB_PATH,
    write: bool = True,
) -> IndexDecompositionResult:
    """Посчитать index_decomposition и (при write=True) записать контрактную таблицу в DuckDB."""
    dec = compute_index_decomposition(features_wide, metric_dim)
    log.info(
        "index_decomposition_built",
        stage="index_decomposition",
        rows=dec.height,
        regions=dec["okato"].n_unique(),
        schemes=dec["weighting_scheme"].n_unique(),
    )
    if write:
        write_table(duckdb_path, "index_decomposition", dec)
    return IndexDecompositionResult(index_decomposition=dec)


if __name__ == "__main__":
    fw = read_table(DEFAULT_DUCKDB_PATH, "features_wide")
    md = read_table(DEFAULT_DUCKDB_PATH, "metric_dim")
    run_index_decomposition(fw, md)
