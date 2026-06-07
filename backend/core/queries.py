"""Параметризованные read-only запросы к контрактным таблицам DuckDB (Ф6).

Единственная точка обращения приложения к аналитическому хранилищу. Изоляция SQL
делает хранилище заменяемым (Хартия §8, swappable storage): при переезде на
ClickHouse/Postgres меняется только этот модуль — API и фронт остаются нетронутыми.
Константы слоёв карты (алгоритм типологии, схема весов индекса) — здесь, т.к. это
«какой слой показываем», а не параметр запроса пользователя.
"""

from __future__ import annotations

from typing import Any

from .duck import q

# Канонические слои карты: типология строится KMeans, базовый индекс — равные веса.
MAP_CLUSTER_ALGO = "kmeans"
MAP_INDEX_SCHEME = "equal"


def geo_layer(year: int, measure: str) -> list[dict[str, Any]]:
    """Слой карты на год: значения по регионам для раскраски (стыковка по okato).

    measure='cluster' → тип региона (cluster_id), осмысленная метка и
    distance_to_centroid (A1: градиент типичности/пограничности — насколько регион
    типичен для своего типа, НЕ вероятность перехода).
    measure='index'   → итоговый индекс развития total_score [0;100].
    """
    if measure == "cluster":
        return q(
            "SELECT okato, cluster_id, cluster_label, distance_to_centroid "
            "FROM clusters WHERE year = ? AND algo = ? ORDER BY okato",
            [year, MAP_CLUSTER_ALGO],
        )
    return q(
        "SELECT okato, total_score "
        "FROM dev_index WHERE year = ? AND weighting_scheme = ? ORDER BY okato",
        [year, MAP_INDEX_SCHEME],
    )


def regions() -> list[dict[str, Any]]:
    """Каталог регионов, участвующих в аналитике (included_flag), для списков/выпадашек.

    Варианты-агрегаты «с/без АО» отфильтрованы (included_flag=false) — остаются только
    85 непересекающихся субъектов. Сортировка по имени — для удобного отображения.
    """
    return q(
        "SELECT okato, region_name, federal_district "
        "FROM region_dim WHERE included_flag = TRUE ORDER BY region_name"
    )


def metrics(domain: str | None = None) -> list[dict[str, Any]]:
    """Каталог метрик ядра (опц. фильтр по домену).

    Ядро отличается от «хвоста» тем, что у него задано направление (higher_is_better
    проставлен только для курируемого ядра в Ф2) — это и используем как дискриминатор.
    """
    sql = (
        "SELECT metric_id, metric_name, domain, unit, value_type, higher_is_better, coverage "
        "FROM metric_dim WHERE higher_is_better IS NOT NULL"
    )
    params: list[Any] = []
    if domain:
        sql += " AND domain = ?"
        params.append(domain)
    sql += " ORDER BY domain, metric_name"
    return q(sql, params)


def metric_series(
    metric_id: int, okato: str, year_from: int | None = None, year_to: int | None = None
) -> list[dict[str, Any]]:
    """Временной ряд метрики по региону из fact_region (полный диапазон годов).

    Полный диапазон (а не окно 2010–2024) — потому что для отображения рядов на
    дашбордах допустимы все годы; окно ограничивает только расчёт аналитики (Хартия §3).
    Параметры from/to — необязательные границы по году. Значения параметризованы (?).
    """
    sql = (
        "SELECT year, value, value_harmonized, is_imputed "
        "FROM fact_region WHERE metric_id = ? AND okato = ?"
    )
    params: list[Any] = [metric_id, okato]
    if year_from is not None:
        sql += " AND year >= ?"
        params.append(year_from)
    if year_to is not None:
        sql += " AND year <= ?"
        params.append(year_to)
    sql += " ORDER BY year"
    return q(sql, params)
