"""Тесты ETL S2: суррогатный metric_id и справочник metric_dim."""

from __future__ import annotations

import polars as pl

from pipeline.etl import attach_metric_id, build_metric_dim


def _metrics_frame() -> pl.DataFrame:
    """5 строк → 4 уникальные пары (indicator_code, subsection), включая null-subsection."""
    return pl.DataFrame(
        {
            "indicator_code": ["0001", "0001", "0001", "0002", "0003"],
            "subsection": ["A", "A", "B", "A", None],
            "indicator_name": ["n1", "n1", "n2", "n3", "n4"],
            "indicator_unit": ["u", "u", "u", "u", "u"],
            "section": ["s", "s", "s", "s", "s"],
            "indicator_value": [1.0, 1.0, 2.0, 3.0, 4.0],
        }
    )


def test_metric_id_unique_per_pair() -> None:
    """Один metric_id на пару (code, subsection); id = 1..N без пропусков."""
    md = build_metric_dim(_metrics_frame())
    assert md.height == 4
    assert md["metric_id"].n_unique() == 4
    assert sorted(md["metric_id"].to_list()) == [1, 2, 3, 4]
    assert set(md.columns) == {
        "metric_id",
        "indicator_code",
        "subsection",
        "metric_name",
        "unit",
        "section",
    }


def test_metric_id_deterministic() -> None:
    """Повторный прогон на тех же данных даёт те же id (воспроизводимость)."""
    df = _metrics_frame()
    assert build_metric_dim(df).to_dicts() == build_metric_dim(df).to_dicts()


def test_attach_metric_id_no_nulls() -> None:
    """Все строки факта получают metric_id, включая строки с пустым subsection."""
    df = _metrics_frame()
    out = attach_metric_id(df, build_metric_dim(df))
    assert out.height == df.height
    assert out["metric_id"].null_count() == 0
