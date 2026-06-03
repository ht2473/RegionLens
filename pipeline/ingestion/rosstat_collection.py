"""Адаптер коллекции Росстата «data_regions_collection_102» (S1).

Читает parquet коллекции через polars, проверяет каноническую схему и приводит типы.
"""
from pathlib import Path

import polars as pl

from pipeline.ingestion.base import SourceAdapter, coerce_to_canonical
from pipeline.logging_setup import log


class RosstatCollectionAdapter(SourceAdapter):
    """Источник: parquet-файл коллекции Росстата (формат long, 14 колонок)."""

    source_id = "rosstat_collection_102"

    def __init__(self, path: str | Path) -> None:
        """path — путь к parquet (берётся из config/sources.yaml)."""
        self.path = Path(path)

    def read(self) -> pl.DataFrame:
        """Прочитать parquet и вернуть DataFrame в канонической схеме."""
        if not self.path.exists():
            raise FileNotFoundError(f"Источник не найден: {self.path}")
        raw = pl.read_parquet(self.path)
        df = coerce_to_canonical(raw, source_id=self.source_id)
        log.info(
            "source_read",
            stage="ingest",
            source=self.source_id,
            path=str(self.path),
            rows=df.height,
            columns=df.width,
        )
        return df
