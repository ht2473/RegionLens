"""Контракт источника данных: абстракция SourceAdapter и каноническая схема.

Точка роста: новый источник = новый адаптер (наследник SourceAdapter) + запись
в config/sources.yaml, без изменения остального конвейера (ETL/признаки/...).
"""

from abc import ABC, abstractmethod

import polars as pl

# Каноническая длинная схема (14 колонок) — единый контракт «сырья» на входе ETL.
# Порядок фиксирован; все адаптеры обязаны возвращать ровно эти колонки.
CANONICAL: list[str] = [
    "section",
    "indicator_code",
    "indicator_name",
    "subsection",
    "object_name",
    "object_level",
    "object_oktmo",
    "object_okato",
    "year",
    "indicator_value",
    "indicator_unit",
    "comment",
    "source",
    "version_date",
]

# Числовые колонки. Всё остальное в CANONICAL приводится к строке (Utf8).
# ВАЖНО: object_okato/object_oktmo — это КОДЫ с возможными ведущими нулями,
# поэтому они строковые (не числа): иначе нули потеряются и сломается ключ региона.
NUMERIC_DTYPES = {
    "year": pl.Int64,
    "indicator_value": pl.Float64,
}


class MissingColumnsError(ValueError):
    """Источник не содержит требуемых колонок канонической схемы."""


def coerce_to_canonical(df: pl.DataFrame, *, source_id: str = "unknown") -> pl.DataFrame:
    """Проверить наличие колонок CANONICAL и привести типы к контрактным.

    Параметры:
        df: сырой DataFrame, прочитанный адаптером.
        source_id: идентификатор источника (для понятного сообщения об ошибке).
    Возвращает:
        DataFrame ровно с колонками CANONICAL (фиксированный порядок) и типами:
        year -> Int64, indicator_value -> Float64, остальные -> Utf8.
    Исключения:
        MissingColumnsError: если хотя бы одной колонки CANONICAL нет.
    """
    missing = [c for c in CANONICAL if c not in df.columns]
    if missing:
        raise MissingColumnsError(
            f"Источник '{source_id}': отсутствуют колонки {missing}. Доступны: {df.columns}"
        )
    string_cols = [c for c in CANONICAL if c not in NUMERIC_DTYPES]
    casts = [pl.col(name).cast(dtype) for name, dtype in NUMERIC_DTYPES.items()]
    casts += [pl.col(c).cast(pl.Utf8) for c in string_cols]
    return df.select(CANONICAL).with_columns(casts)


def null_na_values(df: pl.DataFrame, na_values: list[float] | None) -> pl.DataFrame:
    """Заменить коды «нет данных» в indicator_value на null.

    Росстат кодирует отсутствие данных числами-заглушками (например, -99999999,
    -77777777). Это не значения, а маркеры, поэтому до любой аналитики их надо
    превратить в пропуск — иначе они завышают покрытие и попадают в расчёты.

    Список кодов источник-специфичен и задаётся в config/sources.yaml (na_values).
    Если список пуст или не задан, DataFrame возвращается без изменений.
    """
    if not na_values:
        return df
    codes = [float(v) for v in na_values]
    return df.with_columns(
        pl.when(pl.col("indicator_value").is_in(codes))
        .then(None)
        .otherwise(pl.col("indicator_value"))
        .alias("indicator_value")
    )


class SourceAdapter(ABC):
    """Адаптер источника: читает сырьё и отдаёт DataFrame в схеме CANONICAL.

    Реализация обязана:
      * вернуть ровно колонки CANONICAL в фиксированном порядке;
      * привести типы (см. coerce_to_canonical);
      * бросить MissingColumnsError, если колонок не хватает.
    """

    #: Идентификатор источника (для логов и реестра config/sources.yaml).
    source_id: str = "unknown"

    @abstractmethod
    def read(self) -> pl.DataFrame:
        """Прочитать источник и вернуть DataFrame в канонической схеме."""
        raise NotImplementedError
