"""ETL S2: источники → уровни → metric_id → дедуп → справочники → запись в DuckDB.

Правила грани (Хартия §3): метрика = indicator_code × subsection (грань 1); ключ региона
= object_okato (грань 2); при коллизии изданий — свежайшее (грань 3); аналитика только по
уровню 'Регион' (грань 4). Стадию pandera-валидации + отчёт качества добавит модуль 7.
"""

import importlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl

from pipeline.config import load_config, load_yaml
from pipeline.duck import write_table
from pipeline.ingestion.base import SourceAdapter
from pipeline.logging_setup import configure_logging, log
from pipeline.validation import quality_report, validate_fact_region

# Контролируемый словарь уровней (REFERENCE §1). Именованные константы — не «магия».
LEVEL_REGION = "Регион"
LEVEL_OKRUG = "Федеральный округ"
LEVEL_COUNTRY = "Страна"

# Ключ метрики (грань 1): метрика = indicator_code × subsection.
METRIC_KEY = ["indicator_code", "subsection"]

# Грань факта (грань 3): уникальная запись = okato × метрика × год.
DEDUP_KEY = ["object_okato", "metric_id", "year"]

# Год издания ищем как максимальный 20XX в строке source.
_YEAR_RE = re.compile(r"20\d{2}")

# Путь к аналитическому хранилищу по умолчанию (относительно корня репозитория).
DEFAULT_DUCKDB_PATH = "data/regionlens.duckdb"


@dataclass
class LevelSplit:
    """Разнос канонического факта по уровням объекта (region / okrug / country)."""

    region: pl.DataFrame
    okrug: pl.DataFrame
    country: pl.DataFrame


@dataclass
class EtlResult:
    """Контрактные таблицы S2 — то, что пишется в DuckDB."""

    metric_dim: pl.DataFrame
    region_dim: pl.DataFrame
    fact_region: pl.DataFrame


def build_source_adapters(sources_cfg: list[dict[str, Any]]) -> list[SourceAdapter]:
    """Построить адаптеры из секции `sources` файла config/sources.yaml.

    Каждый источник задаётся dotted-путём класса (`adapter`) и путём к данным (`path`);
    класс резолвится через importlib — новый источник подключается без правки кода ETL.
    """
    adapters: list[SourceAdapter] = []
    for src in sources_cfg:
        module_path, _, cls_name = str(src["adapter"]).rpartition(".")
        cls = getattr(importlib.import_module(module_path), cls_name)
        # na_values пробрасываем, только если источник его объявил — адаптеры без
        # поддержки кодов «нет данных» не обязаны принимать этот аргумент
        kwargs: dict[str, Any] = {}
        if "na_values" in src:
            kwargs["na_values"] = src["na_values"]
        adapters.append(cls(src["path"], **kwargs))
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
        .with_columns(pl.col("metric_id").cast(pl.Int32))
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


def edition_year(source: str | None) -> int:
    """Год издания источника: максимальный 20XX в строке source (0, если нет)."""
    years = [int(y) for y in _YEAR_RE.findall(source or "")]
    return max(years) if years else 0


def deduplicate_by_source(df: pl.DataFrame) -> pl.DataFrame:
    """Дедуп по источнику (грань 3): при коллизии (okato, metric_id, year) оставить
    свежайшее издание — по году в source, затем по version_date. Снятые дубли логируются.
    """
    before = df.height
    deduped = (
        df.with_columns(
            pl.col("source").map_elements(edition_year, return_dtype=pl.Int32).alias("ed_year")
        )
        .sort(
            ["object_okato", "metric_id", "year", "ed_year", "version_date"],
            descending=[False, False, False, True, True],
        )
        .unique(subset=DEDUP_KEY, keep="first")
        .drop("ed_year")
    )
    removed = before - deduped.height
    log.info("etl_dedup", stage="etl", removed=removed, kept=deduped.height)
    return deduped


def is_aggregate_variant(name: str | None) -> bool:
    """Это вариант-агрегат «с/без АО» (Архангельская/Тюменская)?"""
    n = name or ""
    return ("автономным округом" in n) or ("без автономного" in n)


def _variant_kind(name: str | None) -> str:
    """Вид варианта: 'with' (с АО), 'without' (без АО) или 'none' (обычный регион)."""
    n = name or ""
    if "без автономного" in n:
        return "without"
    if "автономным округом" in n:
        return "with"
    return "none"


def build_region_dim(region: pl.DataFrame, regions_cfg: dict[str, Any]) -> pl.DataFrame:
    """Справочник регионов (грань 2: ключ = OKATO).

    federal_district берём из config/regions.yaml (okato→ФО); незамапленные → null
    (логируется, сколько без ФО). included_flag исключает «лишний» вариант «с/без АО»
    по правилу include_with_autonomous_okrug. geojson_key = okato.
    """
    fd_map = regions_cfg.get("federal_districts") or {}
    variants_cfg = regions_cfg.get("aggregate_variants") or {}
    include_with = bool(variants_cfg.get("include_with_autonomous_okrug", True))

    dim = (
        region.select(["object_okato", "object_oktmo", "object_name"])
        .unique(subset="object_okato")
        .rename({"object_okato": "okato", "object_oktmo": "oktmo", "object_name": "region_name"})
        .sort("okato")
        .with_columns(
            pl.col("region_name")
            .map_elements(is_aggregate_variant, return_dtype=pl.Boolean)
            .alias("is_aggregate_variant"),
            pl.col("region_name").map_elements(_variant_kind, return_dtype=pl.Utf8).alias("_vk"),
            pl.col("okato").alias("geojson_key"),
        )
        .with_columns(
            pl.when(pl.col("_vk") == "with")
            .then(pl.lit(include_with))
            .when(pl.col("_vk") == "without")
            .then(pl.lit(not include_with))
            .otherwise(pl.lit(True))
            .alias("included_flag")
        )
        .drop("_vk")
    )

    if fd_map:
        fd_df = pl.DataFrame(
            {"okato": list(fd_map.keys()), "federal_district": list(fd_map.values())},
            schema={"okato": pl.Utf8, "federal_district": pl.Utf8},
        )
        dim = dim.join(fd_df, on="okato", how="left")
    else:
        dim = dim.with_columns(pl.lit(None, dtype=pl.Utf8).alias("federal_district"))

    dim = dim.select(
        [
            "okato",
            "oktmo",
            "region_name",
            "is_aggregate_variant",
            "federal_district",
            "included_flag",
            "geojson_key",
        ]
    )
    log.info(
        "region_dim_built",
        stage="etl",
        regions=dim.height,
        included=dim.filter(pl.col("included_flag")).height,
        missing_federal_district=dim.filter(pl.col("federal_district").is_null()).height,
    )
    return dim


def build_fact_region(region: pl.DataFrame) -> pl.DataFrame:
    """Факт fact_region (грань okato × metric_id × year).

    Базовые поля: okato, metric_id, year, value, source. value_harmonized и is_imputed
    добавит Ф2 (гармонизация форм + импутация).
    """
    return region.select(["object_okato", "metric_id", "year", "indicator_value", "source"]).rename(
        {"object_okato": "okato", "indicator_value": "value"}
    )


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


def write_tables(result: EtlResult, duckdb_path: str) -> None:
    """Записать контрактные таблицы S2 в DuckDB (перезаписью)."""
    write_table(duckdb_path, "fact_region", result.fact_region)
    write_table(duckdb_path, "metric_dim", result.metric_dim)
    write_table(duckdb_path, "region_dim", result.region_dim)
    log.info(
        "duck_written",
        stage="etl",
        path=duckdb_path,
        fact_rows=result.fact_region.height,
        metrics=result.metric_dim.height,
        regions=result.region_dim.height,
    )


def run_etl(
    sources_path: str | Path = "config/sources.yaml",
    duckdb_path: str = DEFAULT_DUCKDB_PATH,
    *,
    write: bool = True,
) -> EtlResult:
    """Полный проход S2: источники → metric_id → уровни → дедуп → справочники → fact_region.

    При write=True пишет fact_region/metric_dim/region_dim в DuckDB. Модуль 7 добавит
    pandera-валидацию и отчёт качества (DoD Ф1).
    """
    configure_logging()
    cfg = load_yaml(sources_path)
    df = read_sources(build_source_adapters(cfg["sources"]))
    log.info("etl_ingested", stage="etl", rows=df.height)
    metric_dim = build_metric_dim(df)
    df = attach_metric_id(df, metric_dim)
    log.info("etl_metrics", stage="etl", metrics=metric_dim.height)
    region = deduplicate_by_source(split_by_level(df).region)
    region_dim = build_region_dim(region, load_config("regions"))
    fact_region = validate_fact_region(build_fact_region(region))
    quality_report(fact_region, metric_dim, region_dim)
    result = EtlResult(metric_dim=metric_dim, region_dim=region_dim, fact_region=fact_region)
    if write:
        write_tables(result, duckdb_path)
    return result


if __name__ == "__main__":
    run_etl()
