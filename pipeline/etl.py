"""ETL S2: загрузка источников, разнос по object_level, суррогатный metric_id.

Региональная аналитика строится ТОЛЬКО на уровне 'Регион'. Уровни 'Федеральный округ'
и 'Страна' выделяются в отдельные слои (контекст/бенчмарк) и в типологию/нормировку
не идут (Хартия §3, правило грани 4). Метрика = indicator_code × subsection
(правило грани 1). Дальнейшие стадии S2 (дедуп, region_dim, fact_region, pandera)
добавляются в следующих модулях Ф1.
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

# Ключ метрики (правило грани 1): метрика = indicator_code × subsection.
METRIC_KEY = ["indicator_code", "subsection"]


@dataclass
class LevelSplit:
    """Разнос канонического факта по уровням объекта (region / okrug / country)."""

    region: pl.DataFrame
    okrug: pl.DataFrame
    country: pl.DataFrame


@dataclass
class EtlResult:
    """Результат S2 (растёт по модулям Ф1): справочник метрик + разнос по уровням."""

    metric_dim: pl.DataFrame
    split: LevelSplit
    # region_dim (модуль 5) и fact_region (модуль 6) добавятся сюда позже.


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


def build_metric_dim(df: pl.DataFrame) -> pl.DataFrame:
    """Справочник метрик: суррогатный metric_id (1..N) по паре (indicator_code, subsection).

    Грань 1: метрика = indicator_code × subsection. metric_id детерминирован
    (стабильная сортировка ключа + индекс строки) → воспроизводим между прогонами.
    Поля domain / value_type / higher_is_better / coverage добавит Ф2.
    """
    return (
        df.select(["indicator_code", "subsection", "indicator_name", "indicator_unit", "section"])
        # сортировка по полному ключу делает выбор представителя имени/единицы детерминированным
        .sort(["indicator_code", "subsection", "indicator_name", "indicator_unit", "section"])
        .unique(subset=METRIC_KEY, keep="first")
        .sort(METRIC_KEY)
        .with_row_index("metric_id", offset=1)
        .rename({"indicator_name": "metric_name", "indicator_unit": "unit"})
        .select(["metric_id", "indicator_code", "subsection", "metric_name", "unit", "section"])
    )


def attach_metric_id(df: pl.DataFrame, metric_dim: pl.DataFrame) -> pl.DataFrame:
    """Добавить metric_id к факту по ключу (indicator_code, subsection).

    nulls_equal=True — чтобы строки с пустым subsection тоже получили id
    (иначе null != null и metric_id оказался бы пустым).
    """
    keys = metric_dim.select(["metric_id", *METRIC_KEY])
    return df.join(keys, on=METRIC_KEY, how="left", nulls_equal=True)


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


def run_etl(sources_path: str | Path = "config/sources.yaml") -> EtlResult:
    """Каркас S2: источники по конфигу → metric_id/metric_dim → разнос по уровням.

    Следующие модули Ф1 добавят сюда: дедуп по источнику, region_dim, запись
    fact_region в DuckDB и pandera-валидацию с отчётом качества.
    """
    configure_logging()
    cfg = load_yaml(sources_path)
    df = read_sources(build_source_adapters(cfg["sources"]))
    log.info("etl_ingested", stage="etl", rows=df.height)
    metric_dim = build_metric_dim(df)
    df = attach_metric_id(df, metric_dim)
    log.info("etl_metrics", stage="etl", metrics=metric_dim.height)
    return EtlResult(metric_dim=metric_dim, split=split_by_level(df))
