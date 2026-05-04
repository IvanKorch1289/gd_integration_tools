"""Аналитические @agent_tool: Polars + DuckDB (Wave 8.5).

Регистрируются через ``ToolRegistry.from_plugin_file(<path>)`` —
prefix будет ``plugin.analytics_tools.*``.
"""

from __future__ import annotations

from typing import Any

from src.services.ai.tools import agent_tool


@agent_tool(
    name="aggregate_polars",
    description="Агрегирует список dict через Polars: group_by + sum/mean/count.",
)
async def aggregate_polars(
    rows: list[dict[str, Any]], group_by: str, value_field: str, op: str = "sum"
) -> list[dict[str, Any]]:
    """Простая агрегация по полю ``group_by``.

    Args:
        rows: Входной dataset (json-like).
        group_by: Поле группировки.
        value_field: Целевое числовое поле.
        op: ``sum`` / ``mean`` / ``count``.

    Returns:
        Список ``{group_by: ..., value_field: ...}``.
    """
    import polars as pl

    if not rows:
        return []
    df = pl.DataFrame(rows)
    match op.lower():
        case "sum":
            agg = pl.col(value_field).sum()
        case "mean":
            agg = pl.col(value_field).mean()
        case "count":
            agg = pl.col(value_field).count()
        case _:
            raise ValueError(f"unknown op: {op!r}")
    out = df.group_by(group_by).agg(agg.alias(value_field))
    return out.to_dicts()


@agent_tool(
    name="query_duckdb",
    description="Выполняет SQL-запрос через DuckDB поверх in-memory list[dict].",
)
async def query_duckdb(
    rows: list[dict[str, Any]], sql: str, table: str = "t"
) -> list[dict[str, Any]]:
    """Регистрирует ``rows`` как таблицу и выполняет SQL.

    Args:
        rows: Источник (json-like).
        sql: SQL-запрос; обращайтесь к таблице по имени ``table``.
        table: Имя зарегистрированной таблицы.

    Returns:
        Список dict — результат запроса.
    """
    import duckdb
    import polars as pl

    df = pl.DataFrame(rows) if rows else pl.DataFrame()
    con = duckdb.connect()
    try:
        con.register(table, df.to_pandas() if rows else df)
        result = con.execute(sql).fetch_df()
        return result.to_dict(orient="records")
    finally:
        con.close()
