"""IO-примитивы DuckDB: запись/чтение контрактных таблиц аналитического хранилища.

Владелец DuckDB-файла — конвейер (пишет). Приложение открывает его read-only (Ф6).
Полиглотное хранение: аналитика — в DuckDB, операционка — в PostgreSQL.
"""

from pathlib import Path

import duckdb
import polars as pl


def write_table(con_path: str, name: str, df: pl.DataFrame) -> None:
    """Записать polars DataFrame в таблицу DuckDB (перезапись, CREATE OR REPLACE).

    `df` виден в SQL через replacement scan DuckDB (нативно, без pyarrow).
    """
    Path(con_path).parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(con_path)
    try:
        con.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM df")
    finally:
        con.close()


def read_table(con_path: str, name: str) -> pl.DataFrame:
    """Прочитать таблицу DuckDB целиком в polars DataFrame (read-only)."""
    con = duckdb.connect(con_path, read_only=True)
    try:
        return con.execute(f"SELECT * FROM {name}").pl()
    finally:
        con.close()


def list_tables(con_path: str) -> list[str]:
    """Список таблиц в DuckDB-файле."""
    con = duckdb.connect(con_path, read_only=True)
    try:
        return [row[0] for row in con.execute("SHOW TABLES").fetchall()]
    finally:
        con.close()
