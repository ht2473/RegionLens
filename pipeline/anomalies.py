"""Аномалии и структурные сдвиги (Ф9 / S8).

Два независимых описательных детектора над предрассчитанными данными:

- **Пространственные выбросы.** По каждому году IsolationForest на матрице признаков
  (регионы × ядро, z_value) помечает регионы, нетипичные на фоне остальных в этот год
  (kind='spatial', metric_id = NULL — выброс по всему профилю).
- **Структурные сдвиги рядов.** По каждому ряду ядра (okato, metric_id) из fact_region
  Binseg (один разрыв на ряд, точная локализация) ищет год смены уровня; кандидат
  принимается, только если ступенчатая подгонка заметно лучше линейного тренда
  (kind='structural_break'). Ряды короткие (~15–25 точек), поэтому требуется минимальная
  длина ряда и порог «ступень vs тренд» — это отсекает плавные тренды и шум.

Результат — контрактная таблица anomalies (REFERENCE §2). Параметры — из
config/analytics.yaml (anomalies); сид — общий проектный (clustering.seed). Детерминизм.

Это диагностика, не причинность: «ряд сменил режим в этом году» / «регион нетипичен для
своего года» — без утверждений о причинах. Сопоставление сдвигов со сменой методологии —
отдельный детектор A3 (следующий модуль).
"""

from dataclasses import dataclass

import numpy as np
import polars as pl
import ruptures as rpt
from sklearn.ensemble import IsolationForest

from pipeline.config import load_config
from pipeline.duck import write_table
from pipeline.logging_setup import log

DEFAULT_DUCKDB_PATH = "data/regionlens.duckdb"

# Контракт anomalies (REFERENCE §2): metric_id NULL для пространственных выбросов.
ANOMALIES_SCHEMA = {
    "okato": pl.Utf8,
    "metric_id": pl.Int32,
    "year": pl.Int32,
    "score": pl.Float64,
    "is_anomaly": pl.Boolean,
    "kind": pl.Utf8,
}


@dataclass
class AnomaliesResult:
    """Итог Ф9: таблица anomalies (пространственные выбросы + структурные сдвиги)."""

    anomalies: pl.DataFrame


def _year_matrix(features_wide: pl.DataFrame, year: int) -> tuple[list[str], np.ndarray]:
    """Матрица года: строки — регионы (okato, по возрастанию), столбцы — ядро (z_value).

    features_wide плотная по ядру (Ф2), поэтому матрица без пропусков. Возвращает
    (okato в порядке строк, матрица регионы×метрики).
    """
    fy = features_wide.filter(pl.col("year") == year)
    wide = fy.pivot(on="metric_id", index="okato", values="z_value").sort("okato")
    value_cols = sorted((c for c in wide.columns if c != "okato"), key=int)
    okato = wide["okato"].to_list()
    matrix = wide.select(value_cols).to_numpy()
    return okato, matrix


def spatial_anomalies(
    features_wide: pl.DataFrame, *, contamination: float, seed: int
) -> list[dict[str, object]]:
    """Пространственные выбросы по годам: IsolationForest на матрице признаков года.

    Для каждого года обучаем IsolationForest и помечаем регионы, нетипичные на фоне
    остальных в этот год. score = decision_function (меньше → аномальнее); is_anomaly —
    предсказание модели (−1). metric_id = NULL (выброс по всему профилю показателей).
    """
    years = sorted(int(y) for y in features_wide["year"].unique().to_list())
    rows: list[dict[str, object]] = []
    for year in years:
        okato, matrix = _year_matrix(features_wide, year)
        if len(okato) < 3:  # IsolationForest бессмысленен на крошечной выборке
            log.info("spatial_year_skipped", stage="anomalies", year=year, regions=len(okato))
            continue
        iso = IsolationForest(contamination=contamination, random_state=seed).fit(matrix)
        scores = iso.decision_function(matrix).tolist()
        flags = iso.predict(matrix).tolist()  # 1 (норма) / −1 (выброс)
        for o, s, f in zip(okato, scores, flags, strict=True):
            rows.append(
                {
                    "okato": o,
                    "metric_id": None,
                    "year": year,
                    "score": float(s),
                    "is_anomaly": bool(f == -1),
                    "kind": "spatial",
                }
            )
    log.info(
        "spatial_anomalies",
        stage="anomalies",
        years=len(years),
        rows=len(rows),
        flagged=sum(1 for r in rows if r["is_anomaly"]),
    )
    return rows


def structural_breaks(
    fact_region: pl.DataFrame,
    core_metric_ids: list[int],
    *,
    model: str,
    max_ratio: float,
    min_len: int,
) -> list[dict[str, object]]:
    """Структурные сдвиги по рядам ядра (okato, metric_id): один разрыв на ряд (Binseg).

    Для каждого ряда (по году, без пропусков) длиной ≥ min_len ищем единственную точку
    смены уровня (Binseg, n_bkps=1, jump=1 — точная локализация). Кандидат принимается как
    структурный сдвиг, только если ступенчатая (двухсегментная) подгонка существенно лучше
    линейной: остаток ступени ≤ max_ratio · остаток линейного тренда. Это масштабонезависимо
    отсекает плавные тренды и шум, оставляя резкие сдвиги уровня. score = величина сдвига
    |Δсреднего|; year = год начала нового режима; is_anomaly=True.
    """
    f = (
        fact_region.filter(
            pl.col("metric_id").is_in(core_metric_ids) & pl.col("value").is_not_null()
        )
        .select(["okato", "metric_id", "year", "value"])
        .sort(["okato", "metric_id", "year"])
    )
    rows: list[dict[str, object]] = []
    n_series = 0
    for grp in f.partition_by(["okato", "metric_id"], maintain_order=True):
        n_series += 1
        years = grp["year"].to_list()
        values = grp["value"].to_numpy().astype(float)
        n = values.shape[0]
        if n < min_len:
            continue
        algo = rpt.Binseg(model=model, min_size=2, jump=1).fit(values.reshape(-1, 1))
        b = int(algo.predict(n_bkps=1)[0])
        if b < 2 or b > n - 2:  # нужно ≥2 точек по обе стороны
            continue
        before, after = values[:b], values[b:]
        x = np.arange(n)
        ss_step = float(((before - before.mean()) ** 2).sum() + ((after - after.mean()) ** 2).sum())
        coef = np.polyfit(x, values, 1)
        ss_lin = float(((values - np.polyval(coef, x)) ** 2).sum())
        # отношение остатков: ступень должна объяснять ряд заметно лучше линейного тренда
        ratio = (
            ss_step / ss_lin if ss_lin > 1e-12 else (0.0 if ss_step < 1e-12 else 1.0 + max_ratio)
        )
        if ratio > max_ratio:
            continue
        rows.append(
            {
                "okato": grp["okato"][0],
                "metric_id": int(grp["metric_id"][0]),
                "year": int(years[b]),
                "score": float(abs(after.mean() - before.mean())),
                "is_anomaly": True,
                "kind": "structural_break",
            }
        )
    log.info("structural_breaks", stage="anomalies", series=n_series, rows=len(rows))
    return rows


def run_anomalies(
    features_wide: pl.DataFrame,
    fact_region: pl.DataFrame,
    *,
    duckdb_path: str = DEFAULT_DUCKDB_PATH,
    write: bool = True,
) -> AnomaliesResult:
    """Ф9 целиком: пространственные выбросы + структурные сдвиги → таблица anomalies.

    Ядро берётся как множество metric_id из features_wide (там только курируемое ядро).
    Параметры и сид — из config/analytics.yaml. Контракт: okato, metric_id (NULL для
    пространственных), year, score, is_anomaly, kind (spatial / structural_break).
    """
    analytics = load_config("analytics")
    cfg = analytics.get("anomalies") or {}
    contamination = float(cfg.get("contamination", 0.05))
    model = str(cfg.get("ruptures_model", "l2"))
    max_ratio = float(cfg.get("max_break_ratio", 0.5))
    min_len = int(cfg.get("min_series_len", 8))
    seed = int((analytics.get("clustering") or {}).get("seed", 42))  # общий проектный сид

    core_metric_ids = sorted(int(m) for m in features_wide["metric_id"].unique().to_list())
    spatial = spatial_anomalies(features_wide, contamination=contamination, seed=seed)
    structural = structural_breaks(
        fact_region, core_metric_ids, model=model, max_ratio=max_ratio, min_len=min_len
    )

    out = pl.DataFrame(spatial + structural, schema=ANOMALIES_SCHEMA).sort(
        ["kind", "okato", "year", "metric_id"]
    )
    log.info(
        "anomalies_built",
        stage="anomalies",
        rows=out.height,
        spatial=len(spatial),
        structural=len(structural),
    )
    if write:
        write_table(duckdb_path, "anomalies", out)
        log.info("anomalies_written", stage="anomalies", path=duckdb_path, rows=out.height)
    return AnomaliesResult(anomalies=out)


if __name__ == "__main__":
    from pipeline.duck import read_table

    fw = read_table(DEFAULT_DUCKDB_PATH, "features_wide")
    fr = read_table(DEFAULT_DUCKDB_PATH, "fact_region")
    run_anomalies(fw, fr)
