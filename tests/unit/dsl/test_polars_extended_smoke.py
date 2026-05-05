"""Wave 7-tail smoke: 5 polars-extended процессоров — конструктор.

polars импортируется внутри `process()` (lazy), поэтому конструкторы
не зависят от наличия polars в среде. Smoke проверяет только контракт
__init__ — кодинг ошибки имени аргументов и обязательных параметров
ловятся как `TypeError`.
"""

from __future__ import annotations

from src.backend.dsl.engine.processors.polars_extended import (
    PolarsAggregateProcessor,
    PolarsJoinProcessor,
    PolarsPivotProcessor,
    PolarsQueryProcessor,
    PolarsWindowProcessor,
)


def test_polars_query_constructs() -> None:
    """PolarsQueryProcessor: дефолтный конструктор + custom-имя."""
    proc = PolarsQueryProcessor(
        select=["id", "amount"],
        filter_expr="amount > 1000",
        with_columns={"tax": "amount * 0.2"},
        sort_by=["id"],
        descending=True,
    )
    assert proc.name == "polars_query"


def test_polars_join_constructs() -> None:
    """PolarsJoinProcessor: required other_path + on, дефолт how=inner."""
    proc = PolarsJoinProcessor(other_path="lookup.customers", on="customer_id")
    assert "polars_join" in proc.name


def test_polars_aggregate_constructs() -> None:
    """PolarsAggregateProcessor: group_by + aggregations."""
    proc = PolarsAggregateProcessor(
        group_by=["status", "kind"],
        aggregations={"total": "sum(amount)", "n": "count(*)"},
    )
    assert proc.name == "polars_aggregate"


def test_polars_pivot_constructs() -> None:
    """PolarsPivotProcessor: index/columns/values + дефолтный agg=sum."""
    proc = PolarsPivotProcessor(
        index="month", columns="region", values="amount"
    )
    assert proc.name == "polars_pivot"


def test_polars_window_constructs() -> None:
    """PolarsWindowProcessor: partition_by + windowed_columns."""
    proc = PolarsWindowProcessor(
        partition_by="customer_id",
        order_by=["created_at"],
        windowed_columns={"rank": "rank()", "running": "sum(amount)"},
    )
    assert proc.name == "polars_window"
