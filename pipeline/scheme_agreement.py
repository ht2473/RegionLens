"""Согласованность рейтингов между схемами весов (модуль «scheme_agreement», лаборатория индекса).

Сводная мера чувствительности индекса к выбору весов: для каждой пары схем (равные/PCA/экспертные)
и каждого года считаем ранговую корреляцию Спирмена между их рейтингами. Близко к 1 ⇒ порядок
регионов почти не зависит от схемы; заметно ниже ⇒ рейтинг — во многом артефакт весов. Дополняет
rank_robustness: там чувствительность по отдельным регионам, здесь — сводно по всему рейтингу и во
времени. Производная описательная мера поверх dev_index (не модель, не прогноз).

Корреляция считается по total_score на совпадающих регионах года (Спирмен = корреляция рангов).
Грань результата — (year, scheme_a, scheme_b); пары неупорядоченные (a<b), чтобы без дублей.
"""

from dataclasses import dataclass
from itertools import combinations

import numpy as np
import polars as pl
from scipy.stats import spearmanr

from pipeline.contracts import SCHEME_AGREEMENT_SCHEMA
from pipeline.duck import read_table, write_table
from pipeline.logging_setup import log

DEFAULT_DUCKDB_PATH = "data/regionlens.duckdb"
MIN_REGIONS = 3  # ниже этого ранговая корреляция непоказательна


def compute_scheme_agreement(dev_index: pl.DataFrame) -> pl.DataFrame:
    """Ранговая корреляция Спирмена между схемами весов по годам (грань year, scheme_a, scheme_b).

    Пивотим dev_index в широкий вид (по схемам), затем для каждого года и каждой пары схем берём
    совпадающие регионы с непустым баллом и считаем Спирмена. Возвращает DataFrame по контракту
    SCHEME_AGREEMENT_SCHEMA, отсортированный по (year, scheme_a, scheme_b).
    """
    schemes = sorted(dev_index["weighting_scheme"].unique().to_list())
    wide = dev_index.pivot(on="weighting_scheme", index=["okato", "year"], values="total_score")
    years = sorted(int(y) for y in wide["year"].unique().to_list())

    rows: list[dict[str, object]] = []
    for year in years:
        sub = wide.filter(pl.col("year") == year)
        for a, b in combinations(schemes, 2):
            pair = sub.select(a, b).drop_nulls()
            if pair.height < MIN_REGIONS:
                continue
            xa = pair[a].to_numpy()
            xb = pair[b].to_numpy()
            rho = float(spearmanr(xa, xb).correlation)
            rows.append(
                {
                    "year": year,
                    "scheme_a": a,
                    "scheme_b": b,
                    "spearman": None if np.isnan(rho) else round(rho, 4),
                    "n_regions": pair.height,
                }
            )

    df = (
        pl.DataFrame(rows, schema=SCHEME_AGREEMENT_SCHEMA)
        if rows
        else pl.DataFrame(schema=SCHEME_AGREEMENT_SCHEMA)
    )
    return df.sort(["year", "scheme_a", "scheme_b"])


@dataclass
class SchemeAgreementResult:
    """Итог модуля: таблица scheme_agreement (корреляция схем по годам)."""

    scheme_agreement: pl.DataFrame


def run_scheme_agreement(
    dev_index: pl.DataFrame,
    *,
    duckdb_path: str = DEFAULT_DUCKDB_PATH,
    write: bool = True,
) -> SchemeAgreementResult:
    """Посчитать scheme_agreement и (при write=True) записать контрактную таблицу в DuckDB."""
    sa = compute_scheme_agreement(dev_index)
    vals = [v for v in sa["spearman"].to_list() if v is not None]
    log.info(
        "scheme_agreement_built",
        stage="scheme_agreement",
        rows=sa.height,
        pairs=sa.select(["scheme_a", "scheme_b"]).unique().height,
        spearman_min=round(min(vals), 4) if vals else None,
        spearman_mean=round(float(np.mean(vals)), 4) if vals else None,
    )
    if write:
        write_table(duckdb_path, "scheme_agreement", sa)
    return SchemeAgreementResult(scheme_agreement=sa)


if __name__ == "__main__":
    dev = read_table(DEFAULT_DUCKDB_PATH, "dev_index")
    run_scheme_agreement(dev)
