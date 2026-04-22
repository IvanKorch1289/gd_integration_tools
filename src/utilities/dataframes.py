"""Dataframe utilities — adapter между polars и pandas (F2, ADR-008).

Новый код использует polars.DataFrame. Для интеграции с legacy
библиотеками и аналитическими notebook-ами — два тонких конвертера.
"""

from __future__ import annotations

from typing import Any

__all__ = ("to_polars", "to_pandas", "read_csv", "read_excel", "write_parquet")


def to_polars(df: Any) -> Any:
    """Конвертирует pandas.DataFrame → polars.DataFrame (no-op если уже polars)."""
    import polars as pl

    if isinstance(df, pl.DataFrame):
        return df
    return pl.from_pandas(df)


def to_pandas(df: Any) -> Any:
    """Конвертирует polars.DataFrame → pandas.DataFrame."""
    import polars as pl

    if not isinstance(df, pl.DataFrame):
        return df
    return df.to_pandas()


def read_csv(path: str, **kwargs: Any) -> Any:
    import polars as pl

    return pl.read_csv(path, **kwargs)


def read_excel(path: str, **kwargs: Any) -> Any:
    import polars as pl

    return pl.read_excel(path, **kwargs)


def write_parquet(df: Any, path: str, **kwargs: Any) -> None:
    import polars as pl

    if not isinstance(df, pl.DataFrame):
        df = pl.from_pandas(df)
    df.write_parquet(path, **kwargs)
