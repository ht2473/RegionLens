"""Тесты аномалий и структурных сдвигов (Ф9 / S8): IsolationForest + ruptures."""

from __future__ import annotations

import polars as pl

from pipeline.anomalies import run_anomalies, spatial_anomalies, structural_breaks


def _features_wide_spatial() -> pl.DataFrame:
    """10 регионов × 2 метрики, год 2015. R0..R8 — компактное облако у нуля, R9 — выброс."""
    cloud = [
        (-0.2, 0.1),
        (0.1, -0.1),
        (0.0, 0.2),
        (-0.1, -0.2),
        (0.2, 0.0),
        (0.1, 0.1),
        (-0.2, -0.1),
        (0.0, -0.2),
        (0.2, 0.2),
    ]
    rows: list[dict[str, object]] = []
    for i, (a, b) in enumerate(cloud):
        for mid, z in zip((10, 20), (a, b), strict=True):
            rows.append(
                {
                    "okato": f"R{i}",
                    "year": 2015,
                    "metric_id": mid,
                    "value_harmonized": 0.0,
                    "z_value": z,
                    "is_imputed": False,
                }
            )
    for mid, z in zip((10, 20), (6.0, -6.0), strict=True):  # R9 — явный выброс
        rows.append(
            {
                "okato": "R9",
                "year": 2015,
                "metric_id": mid,
                "value_harmonized": 0.0,
                "z_value": z,
                "is_imputed": False,
            }
        )
    return pl.DataFrame(rows)


def _fact_series(
    okato: str, metric_id: int, start: int, values: list[float]
) -> list[dict[str, object]]:
    """Ряд fact_region (okato, metric_id) с годами start, start+1, … и заданными значениями."""
    return [
        {
            "okato": okato,
            "metric_id": metric_id,
            "year": start + i,
            "value": float(v),
            "value_harmonized": float(v),
            "source": "s",
            "is_imputed": False,
        }
        for i, v in enumerate(values)
    ]


def test_spatial_flags_clear_outlier() -> None:
    """Пространственный детектор: по строке на регион, R9 помечен, у него минимальный score."""
    rows = spatial_anomalies(_features_wide_spatial(), contamination=0.1, seed=42)
    assert len(rows) == 10
    assert all(r["kind"] == "spatial" and r["metric_id"] is None for r in rows)
    flagged = [r["okato"] for r in rows if r["is_anomaly"]]
    assert "R9" in flagged
    by = {r["okato"]: r["score"] for r in rows}
    assert by["R9"] == min(by.values())  # наиболее аномальный


def test_structural_break_detected_at_shift() -> None:
    """Сдвиг уровня 10→60 на индексе 8 (год 2013) детектируется как structural_break."""
    fr = pl.DataFrame(_fact_series("R0", 10, 2005, [10.0] * 8 + [60.0] * 8))
    rows = structural_breaks(fr, [10], model="l2", max_ratio=0.5, min_len=8)
    assert rows, "ожидался хотя бы один структурный сдвиг"
    assert all(r["kind"] == "structural_break" and r["is_anomaly"] for r in rows)
    assert 2013 in [r["year"] for r in rows]


def test_structural_ignores_linear_trend() -> None:
    """Плавный линейный тренд — НЕ структурный сдвиг (ступень не лучше прямой)."""
    fr = pl.DataFrame(_fact_series("R0", 10, 2005, [float(i) for i in range(16)]))
    assert structural_breaks(fr, [10], model="l2", max_ratio=0.5, min_len=8) == []


def test_structural_skips_short_series() -> None:
    """Ряд короче min_len не анализируется (на коротких рядах детектор осторожен)."""
    fr = pl.DataFrame(_fact_series("R0", 10, 2018, [1.0, 9.0, 1.0]))
    assert structural_breaks(fr, [10], model="l2", max_ratio=0.5, min_len=8) == []


def test_structural_only_core_metrics() -> None:
    """Ряды вне ядра (core_metric_ids) игнорируются."""
    fr = pl.DataFrame(_fact_series("R0", 99, 2005, [10.0] * 8 + [60.0] * 8))
    assert structural_breaks(fr, [10], model="l2", max_ratio=0.5, min_len=8) == []


def test_run_anomalies_schema_kinds_determinism() -> None:
    """run_anomalies: контракт колонок; виды ⊆ {spatial, structural_break}; metric_id NULL
    у пространственных и задан у структурных; повторный прогон идентичен."""
    fw = _features_wide_spatial()
    fr = pl.DataFrame(_fact_series("R0", 10, 2005, [10.0] * 8 + [60.0] * 8))
    out1 = run_anomalies(fw, fr, write=False).anomalies
    assert out1.columns == ["okato", "metric_id", "year", "score", "is_anomaly", "kind"]
    assert set(out1["kind"].unique().to_list()) <= {"spatial", "structural_break"}
    sp = out1.filter(pl.col("kind") == "spatial")
    sb = out1.filter(pl.col("kind") == "structural_break")
    assert sp["metric_id"].null_count() == sp.height
    assert sb.height > 0 and sb["metric_id"].null_count() == 0
    out2 = run_anomalies(fw, fr, write=False).anomalies
    assert out1.equals(out2)
