"""ETL S2: загрузка источников по конфигу и разнос строк по object_level.

Региональная аналитика строится ТОЛЬКО на уровне 'Регион'. Уровни 'Федеральный округ'
и 'Страна' выделяются в отдельные слои (контекст/бенчмарк) и в типологию/нормировку
не идут (Хартия §3, правило грани 4). Дальнейшие стадии S2 (metric_id, дедуп,
region_dim, fact_region, pandera) добавляются в следующих модулях Ф1.
"""

import importlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl

from pipeline.config import load_yaml
from pipeline.ingestion.base import SourceAdapter
from pipeline.logging_setup import configure_logging, log

# Контролируемый словарь уровней (REFERENCE §1). Именованные константы — не «магия».
LEVEL_REGION = "Регион"
LEVEL_OKRUG = "Федеральный округ"
LEVEL_COUNTRY = "Страна"


@dataclass
class LevelSplit:
    """Разнос канонического факта по уровням объекта (region / okrug / country)."""

    region: pl.DataFrame
    okrug: pl.DataFrame
    country: pl.DataFrame


def build_source_adapters(sources_cfg: list[dict[str, Any]]) -> list[SourceAdapter]:
    """Построить адаптеры из секции `sources` файла config/sources.yaml.

    Каждый источник задаётся dotted-путём класса (`adapter`) и путём к данным (`path`);
    класс резолвится через importlib — новый источник подключается без правки кода ETL.
    """
    adapters: list[SourceAdapter] = []
    for src in sources_cfg:
        module_path, _, cls_name = str(src["adapter"]).rpartition(".")
        cls = getattr(importlib.import_module(module_path), cls_name)
        adapters.append(cls(src["path"]))
    return adapters


def read_sources(adapters: list[SourceAdapter]) -> pl.DataFrame:
    """Прочитать все источники и склеить в один канонический DataFrame."""
    if not adapters:
        raise ValueError("Не задано ни одного источника (секция sources пуста).")
    frames = [a.read() for a in adapters]
    return frames[0] if len(frames) == 1 else pl.concat(frames, how="vertical")


def split_by_level(df: pl.DataFrame) -> LevelSplit:
    """Разнести строки по object_level: регион / федеральный округ / страна.

    Строки с неизвестным уровнем не попадают ни в один слой и логируются (контроль
    качества), чтобы потеря данных была видимой, а не тихой.
    """
    region = df.filter(pl.col("object_level") == LEVEL_REGION)
    okrug = df.filter(pl.col("object_level") == LEVEL_OKRUG)
    country = df.filter(pl.col("object_level") == LEVEL_COUNTRY)
    other = df.height - region.height - okrug.height - country.height
    if other:
        log.warning("etl_unknown_levels", stage="etl", rows=other)
    log.info(
        "etl_level_split",
        stage="etl",
        region=region.height,
        okrug=okrug.height,
        country=country.height,
    )
    return LevelSplit(region=region, okrug=okrug, country=country)


def run_etl(sources_path: str | Path = "config/sources.yaml") -> LevelSplit:
    """Каркас S2: загрузить источники по конфигу и разнести по уровням.

    Следующие модули Ф1 добавят сюда: metric_id + metric_dim, дедуп по источнику,
    region_dim, запись fact_region в DuckDB и pandera-валидацию с отчётом качества.
    """
    configure_logging()
    cfg = load_yaml(sources_path)
    adapters = build_source_adapters(cfg["sources"])
    df = read_sources(adapters)
    log.info("etl_ingested", stage="etl", rows=df.height)
    return split_by_level(df)
