"""Адаптер коллекции Росстата «data_regions_collection_102».

Читает parquet коллекции через polars, проверяет каноническую схему и приводит типы.
"""

from pathlib import Path

import polars as pl

from pipeline.ingestion.base import SourceAdapter, coerce_to_canonical, null_na_values
from pipeline.logging_setup import log


class RosstatCollectionAdapter(SourceAdapter):
    """Источник: parquet-файл коллекции Росстата (формат long, 14 колонок)."""

    source_id = "rosstat_collection_102"

    def __init__(self, path: str | Path, *, na_values: list[float] | None = None) -> None:
        """path — путь к parquet; na_values — коды «нет данных» (из config/sources.yaml)."""
        self.path = Path(path)
        self.na_values = na_values or []

    def read(self) -> pl.DataFrame:
        """Прочитать parquet, привести к канону и занулить коды «нет данных»."""
        if not self.path.exists():
            raise FileNotFoundError(f"Источник не найден: {self.path}")
        raw = pl.read_parquet(self.path)
        df = coerce_to_canonical(raw, source_id=self.source_id)
        # сколько заглушек встретилось — в лог, чтобы потеря была видимой, а не тихой
        codes = [float(v) for v in self.na_values]
        na_hits = 0
        if codes:
            na_hits = int(df.select(pl.col("indicator_value").is_in(codes).sum()).item())
        df = null_na_values(df, self.na_values)
        log.info(
            "source_read",
            stage="ingest",
            source=self.source_id,
            path=str(self.path),
            rows=df.height,
            columns=df.width,
            na_nulled=na_hits,
        )
        return df
