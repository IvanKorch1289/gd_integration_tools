"""Тонкие polars-обёртки для чтения/записи табличных данных.

В проекте используется только polars (pandas удалён). Этот модуль —
исторический shortcut для CSV/Excel/Parquet I/O без бизнес-логики.

Для табличных операций приложения смотри ``src.services.io.dataframe``.
"""

from typing import Any

import polars as pl

__all__ = ("read_csv", "read_excel", "write_parquet")


def read_csv(path: str, **kwargs: Any) -> pl.DataFrame:
    """Читает CSV-файл в polars DataFrame.

    Тонкая обёртка над ``polars.read_csv``; прокидывает все kwargs напрямую.

    Args:
        path: Путь к CSV-файлу (локальный, S3, http — per polars docs).
        **kwargs: Передаются в ``polars.read_csv`` без изменений
            (separator, has_header, schema_overrides, null_values, etc.).

    Returns:
        pl.DataFrame с распарсенными данными.

    Example:
        >>> df = read_csv("data.csv", separator=";")
    """
    return pl.read_csv(path, **kwargs)


def read_excel(path: str, **kwargs: Any) -> pl.DataFrame:
    """Читает Excel-файл в polars DataFrame.

    Тонкая обёртка над ``polars.read_excel``; прокидывает все kwargs.

    Args:
        path: Путь к .xlsx/.xls файлу.
        **kwargs: Передаются в ``polars.read_excel`` (sheet_name, etc.).

    Returns:
        pl.DataFrame с распарсенными данными.
    """
    return pl.read_excel(path, **kwargs)


def write_parquet(df: pl.DataFrame, path: str, **kwargs: Any) -> None:
    """Сохраняет polars DataFrame в Parquet-файл.

    Тонкая обёртка над ``pl.DataFrame.write_parquet``; прокидывает kwargs.

    Args:
        df: Polars DataFrame для записи.
        path: Целевой путь (локальный, S3, etc. — per polars docs).
        **kwargs: Передаются в ``write_parquet`` (compression, compression_level,
            statistics, row_group_size, etc.).
    """
    df.write_parquet(path, **kwargs)
