"""Dataframe abstraction — Polars-first.

Polars (Rust-backed) — единственный движок таблиц в проекте. Использует
Apache Arrow memory model (zero-copy с Parquet/Arrow), быстрее pandas
на CSV/Parquet, GroupBy, Joins и поддерживает lazy evaluation.

Usage::

    from src.backend.services.io.dataframe import read_csv, write_excel, to_records

    df = read_csv(buffer)        # polars.DataFrame
    rows = to_records(df)        # list[dict] для service-API совместимости
    write_excel(rows, output_path)
"""

import io
import logging
from typing import Any, Iterable

import polars as pl

__all__ = (
    "read_csv",
    "read_excel",
    "write_csv",
    "write_excel",
    "to_records",
    "from_records",
    "DataFrame",
)

logger = logging.getLogger("services.dataframe")

DataFrame = pl.DataFrame


def from_records(records: Iterable[dict[str, Any]]) -> pl.DataFrame:
    """list[dict] → polars.DataFrame."""
    records_list = list(records)
    return pl.DataFrame(records_list) if records_list else pl.DataFrame()


def to_records(df: pl.DataFrame | None) -> list[dict[str, Any]]:
    """polars.DataFrame → list[dict] (совместимо со старыми service-API)."""
    if df is None:
        return []
    return df.to_dicts()


def read_csv(source: Any) -> pl.DataFrame:
    """Читает CSV из bytes / path / inline-строки."""
    if isinstance(source, str) and not source.startswith(("/", "s3://")):
        return pl.read_csv(io.StringIO(source))
    if isinstance(source, bytes):
        return pl.read_csv(io.BytesIO(source))
    return pl.read_csv(source)


def read_excel(source: Any, *, sheet_name: str | int = 0) -> pl.DataFrame:
    """Читает Excel через polars (calamine/openpyxl backend)."""
    return pl.read_excel(source, sheet_name=sheet_name)


def write_csv(df: pl.DataFrame, path: str | None = None) -> bytes | None:
    """polars.DataFrame → CSV bytes (или write в файл)."""
    if path:
        df.write_csv(path)
        return None
    buf = io.BytesIO()
    df.write_csv(buf)
    return buf.getvalue()


def write_excel(
    data: pl.DataFrame | list[dict[str, Any]],
    path: str | None = None,
    *,
    sheet_name: str = "Sheet1",
) -> bytes | None:
    """polars.DataFrame или list[dict] → Excel bytes (или write в файл).

    polars.write_excel использует xlsxwriter.
    """
    df = from_records(data) if isinstance(data, (list, tuple)) else data

    if path:
        df.write_excel(path, worksheet=sheet_name)
        return None

    buf = io.BytesIO()
    df.write_excel(buf, worksheet=sheet_name)
    return buf.getvalue()
