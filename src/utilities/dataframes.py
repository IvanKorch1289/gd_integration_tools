"""Тонкие polars-обёртки для чтения/записи табличных данных.

В проекте используется только polars (pandas удалён). Этот модуль —
исторический shortcut для CSV/Excel/Parquet I/O без бизнес-логики.

Для табличных операций приложения смотри ``src.services.io.dataframe``.
"""


from typing import Any

import polars as pl

__all__ = ("read_csv", "read_excel", "write_parquet")


def read_csv(path: str, **kwargs: Any) -> pl.DataFrame:
    return pl.read_csv(path, **kwargs)


def read_excel(path: str, **kwargs: Any) -> pl.DataFrame:
    return pl.read_excel(path, **kwargs)


def write_parquet(df: pl.DataFrame, path: str, **kwargs: Any) -> None:
    df.write_parquet(path, **kwargs)
