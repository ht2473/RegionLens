"""Тесты ETL: дедуп по источнику (правило грани 3 — свежайшее издание)."""

from __future__ import annotations

import polars as pl

from pipeline.etl import deduplicate_by_source, edition_year


def test_edition_year_extracts_max_year() -> None:
    """Год издания = максимальный 20XX в строке source; иначе 0."""
    assert edition_year("Регионы России 2020") == 2020
    assert edition_year("издание 2018, ревизия 2021") == 2021
    assert edition_year("без года") == 0
    assert edition_year(None) == 0


def test_dedup_keeps_freshest_edition() -> None:
    """При коллизии (okato, metric_id, year) остаётся запись из свежайшего издания."""
    df = pl.DataFrame(
        {
            "object_okato": ["92000000000", "92000000000", "01000000000"],
            "metric_id": [1, 1, 1],
            "year": [2015, 2015, 2015],
            "source": ["Сборник 2018", "Сборник 2021", "Сборник 2020"],
            "version_date": ["2018-12-31", "2021-12-31", "2020-12-31"],
            "indicator_value": [100.0, 110.0, 50.0],
        }
    )
    out = deduplicate_by_source(df)
    assert out.height == 2  # дубль (okato 9200..., 2015) схлопнут
    kept = out.filter(pl.col("object_okato") == "92000000000").row(0, named=True)
    assert kept["source"] == "Сборник 2021"
    assert kept["indicator_value"] == 110.0
    assert "ed_year" not in out.columns  # служебная колонка удалена


def test_dedup_keeps_all_when_no_collision() -> None:
    """Без коллизий по ключу дедуп ничего не удаляет."""
    df = pl.DataFrame(
        {
            "object_okato": ["a", "b"],
            "metric_id": [1, 1],
            "year": [2015, 2015],
            "source": ["s 2020", "s 2020"],
            "version_date": ["2020-01-01", "2020-01-01"],
            "indicator_value": [1.0, 2.0],
        }
    )
    assert deduplicate_by_source(df).height == 2
