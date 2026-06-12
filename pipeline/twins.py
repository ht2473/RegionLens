"""Статистические двойники регионов (фича C2).

Производная мера поверх готовых z-score из features_wide: для каждого года окна считаем
косинусную близость профилей регионов (вектор z_value по ядру метрик) и сохраняем top-N
ближайших на регион-год в контрактную таблицу region_twins (DuckDB).

Двойники = статистическое сходство профиля показателей в конкретный год. Это НЕ обучаемая
модель, НЕ прогноз и НЕ причинность — стоп-правило «нет новых аналитических моделей» не
нарушается (это арифметика над уже посчитанными z_value).

Параметр top_n — из config/analytics.yaml (twins.top_n); никакого хардкода.
"""

from dataclasses import dataclass

import numpy as np
import polars as pl

from pipeline.config import load_config
from pipeline.duck import write_table
from pipeline.logging_setup import log

DEFAULT_DUCKDB_PATH = "data/regionlens.duckdb"

# Контракт region_twins (REFERENCE §2): порядок и типы колонок.
TWINS_SCHEMA = {
    "okato": pl.Utf8,
    "year": pl.Int32,
    "twin_okato": pl.Utf8,
    "similarity": pl.Float64,
    "rank": pl.Int32,
}


@dataclass
class TwinsResult:
    """Итог C2: таблица region_twins (top-N двойников на регион-год)."""

    twins: pl.DataFrame


def build_year_matrix(features_wide: pl.DataFrame, year: int) -> tuple[list[str], np.ndarray]:
    """Матрица профилей за год: строки — регионы (okato), столбцы — метрики ядра (z_value).

    Порядок строк (okato) и столбцов (metric_id) детерминирован сортировкой ради
    воспроизводимости. Предполагается полнота ядра в features_wide (Ф2): без пропусков,
    иначе пустые ячейки исказили бы близость. Возвращает (okatos, matrix) с
    matrix.shape == (n_regions, n_metrics).
    """
    yr = features_wide.filter(pl.col("year") == year).select(["okato", "metric_id", "z_value"])
    wide = yr.pivot(on="metric_id", index="okato", values="z_value").sort("okato")
    okatos = wide["okato"].to_list()
    # колонки после pivot названы строковыми metric_id — сортируем по числовому значению
    value_cols = sorted((c for c in wide.columns if c != "okato"), key=int)
    matrix = wide.select(value_cols).to_numpy()
    return okatos, matrix


def cosine_matrix(matrix: np.ndarray) -> np.ndarray:
    """Попарная косинусная близость строк-профилей: (n×m) → (n×n), значения в [−1; 1].

    Нулевой профиль (норма 0) защищён от деления на ноль: его близость со всеми = 0.
    """
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    safe = np.where(norms == 0.0, 1.0, norms)
    normed = matrix / safe
    return normed @ normed.T


def twins_for_year(
    okatos: list[str], sim: np.ndarray, year: int, top_n: int
) -> list[dict[str, object]]:
    """top-N двойников каждого региона за год по убыванию близости (сам регион исключён).

    Тай-брейк при равной близости — по okato (лексикографически), для детерминизма.
    rank: 1 — самый похожий. Возвращает строки-словари контракта region_twins.
    """
    okato_arr = np.array(okatos)
    rows: list[dict[str, object]] = []
    for i, okato in enumerate(okatos):
        s = sim[i].copy()
        s[i] = -np.inf  # исключаем сам регион из списка двойников
        # первичный ключ — −s (по убыванию близости), вторичный — okato (по возрастанию)
        order = np.lexsort((okato_arr, -s))
        for rank, j in enumerate(order[:top_n].tolist(), start=1):
            rows.append(
                {
                    "okato": okato,
                    "year": year,
                    "twin_okato": okatos[j],
                    "similarity": float(sim[i, j]),
                    "rank": rank,
                }
            )
    return rows


def run_twins(
    features_wide: pl.DataFrame,
    *,
    duckdb_path: str = DEFAULT_DUCKDB_PATH,
    write: bool = True,
    top_n: int | None = None,
) -> TwinsResult:
    """Фича C2 целиком: по каждому году окна — косинусная близость профилей → top-N → запись.

    Итоговая таблица region_twins (контракт REFERENCE §2): okato, year, twin_okato,
    similarity, rank. top_n берётся из config/analytics.yaml (twins.top_n), если не задан.
    """
    if top_n is None:
        cfg = load_config("analytics").get("twins") or {}
        top_n = int(cfg.get("top_n", 5))

    years = sorted(int(y) for y in features_wide["year"].unique().to_list())
    all_rows: list[dict[str, object]] = []
    for year in years:
        okatos, matrix = build_year_matrix(features_wide, year)
        if len(okatos) < 2:
            log.info("twins_year_skipped", stage="twins", year=year, regions=len(okatos))
            continue
        sim = cosine_matrix(matrix)
        all_rows.extend(twins_for_year(okatos, sim, year, top_n))

    out = pl.DataFrame(all_rows, schema=TWINS_SCHEMA).sort(["year", "okato", "rank"])
    log.info(
        "twins_built",
        stage="twins",
        rows=out.height,
        years=len(years),
        top_n=top_n,
        regions=(out["okato"].n_unique() if out.height else 0),
    )
    if write:
        write_table(duckdb_path, "region_twins", out)
        log.info("twins_written", stage="twins", path=duckdb_path, rows=out.height)
    return TwinsResult(twins=out)


if __name__ == "__main__":
    from pipeline.duck import read_table

    fw = read_table(DEFAULT_DUCKDB_PATH, "features_wide")
    run_twins(fw)
