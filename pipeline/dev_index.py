"""Композитный индекс развития регионов.

Из features_wide (z_value) и metric_dim (domain, higher_is_better) строим доменные
баллы с учётом направления метрики, сводим их в итог по нескольким схемам весов
(equal / PCA / expert), нормируем итог в [0;100] единым по всему окну преобразованием
и оцениваем чувствительность рейтинга к выбору схемы (ранговая корреляция Спирмена).
Результат — таблица dev_index.

Параметры — из config/weights.yaml; никакого хардкода весов в коде.
"""

from dataclasses import dataclass

import numpy as np
import polars as pl
from scipy.stats import spearmanr
from sklearn.decomposition import PCA

from pipeline.config import load_config
from pipeline.duck import write_table
from pipeline.logging_setup import log

# Порядок доменных колонок в dev_index (контракт схемы таблицы).
DOMAIN_COLS = ["economy", "income", "demography", "labor", "infrastructure", "health_edu"]
DEFAULT_DUCKDB_PATH = "data/regionlens.duckdb"


@dataclass
class DevIndexResult:
    """Итог Ф4: таблица индекса по схемам весов."""

    dev_index: pl.DataFrame


def compute_domain_scores(features_wide: pl.DataFrame, metric_dim: pl.DataFrame) -> pl.DataFrame:
    """Доменные баллы: средний z со знаком направления по (okato, year, domain) → широкая форма.

    z_signed = z_value × (+1, если higher_is_better, иначе −1) — чтобы больший балл всегда
    означал «лучше». Затем усредняем по метрикам домена. Возвращает okato, year + колонка
    на каждый домен.
    """
    md = metric_dim.select(["metric_id", "domain", "higher_is_better"])
    fw = features_wide.join(md, on="metric_id", how="inner").with_columns(
        (pl.col("z_value") * pl.when(pl.col("higher_is_better")).then(1.0).otherwise(-1.0)).alias(
            "z_signed"
        )
    )
    dom = fw.group_by(["okato", "year", "domain"]).agg(pl.col("z_signed").mean().alias("dscore"))
    return dom.pivot(on="domain", index=["okato", "year"], values="dscore").sort(["okato", "year"])


def scheme_weights(
    domain_matrix: np.ndarray, domains: list[str], scheme: str, expert: dict[str, float]
) -> np.ndarray:
    """Веса доменов для схемы (в порядке domains). equal — поровну; pca — нагрузки 1-й
    компоненты (ориентированы положительно, сумма 1); expert — из конфига (перенормированы)."""
    n = len(domains)
    if scheme == "equal":
        return np.full(n, 1.0 / n)
    if scheme == "pca":
        comp = PCA(n_components=1).fit(domain_matrix).components_[0]
        if comp.sum() < 0:  # ориентируем компоненту положительно
            comp = -comp
        total = comp.sum()
        return comp / total if total != 0 else np.full(n, 1.0 / n)
    if scheme == "expert":
        raw = np.array([float(expert.get(d, 0.0)) for d in domains])
        total = raw.sum()
        return raw / total if total > 0 else np.full(n, 1.0 / n)
    raise ValueError(f"Неизвестная схема весов: {scheme}")


def to_100(values: np.ndarray) -> np.ndarray:
    """Линейная нормировка в [0;100] по всему окну (единый min/max, не по годам).

    Единое преобразование сохраняет динамику: рост региона во времени отражается в индексе
    (важно для траекторий Ф5). Вырожденный случай (все значения равны) → 50.
    """
    lo, hi = float(np.nanmin(values)), float(np.nanmax(values))
    if hi <= lo:
        return np.full_like(values, 50.0)
    return 100.0 * (values - lo) / (hi - lo)


def _log_sensitivity(dev_index: pl.DataFrame, schemes: list[str]) -> None:
    """Чувствительность рейтинга: ранговая корреляция Спирмена между схемами по годам."""
    if "equal" not in schemes or "pca" not in schemes:
        return
    years = sorted(int(y) for y in dev_index["year"].unique().to_list())
    rhos = []
    for year in years:
        eq = (
            dev_index.filter((pl.col("year") == year) & (pl.col("weighting_scheme") == "equal"))
            .sort("okato")["total_score"]
            .to_numpy()
        )
        pc = (
            dev_index.filter((pl.col("year") == year) & (pl.col("weighting_scheme") == "pca"))
            .sort("okato")["total_score"]
            .to_numpy()
        )
        rhos.append(float(spearmanr(eq, pc).correlation))
    log.info(
        "dev_index_sensitivity",
        stage="dev_index",
        spearman_equal_vs_pca_mean=round(float(np.mean(rhos)), 4),
        spearman_min=round(float(np.min(rhos)), 4),
    )


def build_dev_index(features_wide: pl.DataFrame, metric_dim: pl.DataFrame) -> pl.DataFrame:
    """Собрать dev_index по всем схемам весов + залогировать чувствительность рейтинга."""
    weights_cfg = load_config("weights")
    schemes = list((weights_cfg.get("schemes") or {}).keys())
    expert = (weights_cfg.get("schemes") or {}).get("expert") or {}

    wide = compute_domain_scores(features_wide, metric_dim)
    domains = [c for c in wide.columns if c not in ("okato", "year")]
    domain_matrix = wide.select(domains).to_numpy()

    frames: list[pl.DataFrame] = []
    for scheme in schemes:
        weights = scheme_weights(domain_matrix, domains, scheme, expert)
        total = to_100(domain_matrix @ weights)
        frames.append(
            wide.with_columns(
                pl.lit(scheme).alias("weighting_scheme"),
                pl.Series("total_score", total),
            )
        )
        log.info(
            "dev_index_scheme",
            stage="dev_index",
            scheme=scheme,
            weights=dict(zip(domains, (round(float(w), 3) for w in weights), strict=True)),
        )

    dev = pl.concat(frames)
    # привести к контрактному набору доменных колонок (отсутствующие → null)
    for col in DOMAIN_COLS:
        if col not in dev.columns:
            dev = dev.with_columns(pl.lit(None, dtype=pl.Float64).alias(col))
    dev = dev.select(["okato", "year", "weighting_scheme", "total_score", *DOMAIN_COLS]).sort(
        ["weighting_scheme", "year", "okato"]
    )
    _log_sensitivity(dev, schemes)
    log.info("dev_index_built", stage="dev_index", rows=dev.height, schemes=schemes)
    return dev


def run_dev_index(
    features_wide: pl.DataFrame,
    metric_dim: pl.DataFrame,
    *,
    duckdb_path: str = DEFAULT_DUCKDB_PATH,
    write: bool = True,
) -> DevIndexResult:
    """Ф4 целиком: доменные баллы → схемы весов → нормировка → dev_index (+запись в DuckDB)."""
    dev = build_dev_index(features_wide, metric_dim)
    if write:
        write_table(duckdb_path, "dev_index", dev)
        log.info("dev_index_written", stage="dev_index", path=duckdb_path, rows=dev.height)
    return DevIndexResult(dev_index=dev)


if __name__ == "__main__":
    from pipeline.duck import read_table

    fw = read_table(DEFAULT_DUCKDB_PATH, "features_wide")
    md = read_table(DEFAULT_DUCKDB_PATH, "metric_dim")
    run_dev_index(fw, md)
