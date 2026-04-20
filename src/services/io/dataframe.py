"""Dataframe abstraction — Polars-first, pandas fallback.

Polars (Rust-backed) в 5-30x быстрее pandas на:
- CSV/Parquet read/write
- GroupBy + aggregations
- Joins, filters, transformations
- Lazy evaluation (deferred computation)

Дополнительно Polars использует Apache Arrow memory model
(zero-copy с Parquet/Arrow), ниже memory footprint.

Usage::

    from app.services.io.dataframe import read_csv, write_excel, to_records

    df = read_csv(buffer)  # Polars DataFrame
    rows = to_records(df)  # list[dict] для обратной совместимости
    write_excel(rows, output_path)
"""

from __future__ import annotations

import logging
from typing import Any, Iterable

__all__ = (
    "POLARS_AVAILABLE",
    "read_csv",
    "read_excel",
    "write_csv",
    "write_excel",
    "to_records",
    "from_records",
    "DataFrame",
)

logger = logging.getLogger("services.dataframe")


try:
    import polars as _pl
    POLARS_AVAILABLE = True
    DataFrame = _pl.DataFrame
except ImportError:
    POLARS_AVAILABLE = False
    DataFrame = Any  # type: ignore[misc,assignment]


def from_records(records: Iterable[dict[str, Any]]) -> Any:
    """list[dict] → DataFrame (Polars или pandas)."""
    records_list = list(records)
    if POLARS_AVAILABLE:
        return _pl.DataFrame(records_list) if records_list else _pl.DataFrame()

    import pandas as pd
    return pd.DataFrame(records_list)


def to_records(df: Any) -> list[dict[str, Any]]:
    """DataFrame → list[dict] (совместимо со старыми service APIs)."""
    if df is None:
        return []
    if POLARS_AVAILABLE and hasattr(df, "to_dicts"):
        return df.to_dicts()
    if hasattr(df, "to_dict"):
        return df.to_dict(orient="records")
    return []


def read_csv(source: Any) -> Any:
    """Читает CSV из bytes/path/str. Возвращает DataFrame.

    Polars: 5-10x быстрее pandas на больших файлах.
    """
    if POLARS_AVAILABLE:
        import io
        if isinstance(source, str) and not source.startswith(("/", "s3://")):
            return _pl.read_csv(io.StringIO(source))
        if isinstance(source, bytes):
            return _pl.read_csv(io.BytesIO(source))
        return _pl.read_csv(source)

    import io
    import pandas as pd
    if isinstance(source, str) and not source.startswith(("/", "s3://")):
        return pd.read_csv(io.StringIO(source))
    if isinstance(source, bytes):
        return pd.read_csv(io.BytesIO(source))
    return pd.read_csv(source)


def read_excel(source: Any, *, sheet_name: str | int = 0) -> Any:
    """Читает Excel. Polars использует calamine (rust), pandas — openpyxl."""
    if POLARS_AVAILABLE:
        try:
            return _pl.read_excel(source, sheet_name=sheet_name)
        except Exception as exc:
            logger.debug("Polars read_excel failed, falling back to pandas: %s", exc)

    import pandas as pd
    return pd.read_excel(source, sheet_name=sheet_name)


def write_csv(df: Any, path: str | None = None) -> bytes | None:
    """DataFrame → CSV bytes (или write в файл)."""
    if POLARS_AVAILABLE and hasattr(df, "write_csv"):
        if path:
            df.write_csv(path)
            return None
        import io
        buf = io.BytesIO()
        df.write_csv(buf)
        return buf.getvalue()

    if path:
        df.to_csv(path, index=False)
        return None
    return df.to_csv(index=False).encode("utf-8")


def write_excel(
    data: Any,
    path: str | None = None,
    *,
    sheet_name: str = "Sheet1",
) -> bytes | None:
    """DataFrame или list[dict] → Excel bytes (или write в файл).

    Polars write_excel использует xlsxwriter (fast).
    """
    if not isinstance(data, (list, tuple)) and POLARS_AVAILABLE and hasattr(data, "write_excel"):
        if path:
            data.write_excel(path, worksheet=sheet_name)
            return None
        import io
        buf = io.BytesIO()
        data.write_excel(buf, worksheet=sheet_name)
        return buf.getvalue()

    if isinstance(data, list):
        df = from_records(data)
    else:
        df = data

    import io
    if POLARS_AVAILABLE and hasattr(df, "write_excel"):
        if path:
            df.write_excel(path, worksheet=sheet_name)
            return None
        buf = io.BytesIO()
        df.write_excel(buf, worksheet=sheet_name)
        return buf.getvalue()

    import pandas as pd
    if isinstance(df, pd.DataFrame):
        if path:
            df.to_excel(path, sheet_name=sheet_name, index=False)
            return None
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name=sheet_name, index=False)
        return buf.getvalue()

    raise TypeError(f"Unsupported data type for write_excel: {type(df)}")
