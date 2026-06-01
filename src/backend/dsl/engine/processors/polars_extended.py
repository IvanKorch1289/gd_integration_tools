"""Wave 7.2 — polars-extended DSL-процессоры (query/join/aggregate/pivot/window).

Назначение: дать DSL-route'ам возможность делать аналитические операции
поверх ``exchange.in_message.body`` без выгрузки в SQL-движок. Polars
быстрее pandas (Rust-реализация), уже есть в стеке проекта (>=1.20).

Контракт процессоров:

* Принимают ``body`` как ``list[dict]`` (rows-of-dicts) — стандартная
  форма JSON-payload в DSL.
* Возвращают результат тоже как ``list[dict]`` (через
  ``DataFrame.to_dicts()``) — совместимо с downstream-процессорами.
* Polars импортируется ленивно — отсутствие polars не должно ломать
  импорт модуля.

Все процессоры — pure (``side_effect=PURE``), идемпотентны.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, ClassVar, Literal

from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.processors.base import BaseProcessor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

__all__ = (
    "PolarsAggregateProcessor",
    "PolarsJoinProcessor",
    "PolarsPivotProcessor",
    "PolarsQueryProcessor",
    "PolarsWindowProcessor",
)

_logger = logging.getLogger("dsl.polars")

JoinHow = Literal["inner", "left", "right", "outer", "semi", "anti", "cross"]


def _ensure_dataframe(body: Any) -> Any:
    """Конвертирует ``body`` в polars DataFrame (lazy import polars).

    Принимает ``list[dict]`` либо уже готовый ``pl.DataFrame``. Иначе —
    оборачивает single dict в одно-строчный DataFrame.
    """
    import polars as pl

    if isinstance(body, pl.DataFrame):
        return body
    if isinstance(body, list):
        return pl.DataFrame(body) if body else pl.DataFrame()
    if isinstance(body, dict):
        return pl.DataFrame([body])
    raise TypeError(
        f"Polars-процессор ожидает list[dict] / dict / DataFrame, "
        f"получил {type(body).__name__}"
    )


class PolarsQueryProcessor(BaseProcessor):
    """Wave 7.2 — выполнение polars-выражений (filter/select/with_columns).

    Выражение задаётся как dict-операций (декларативно), а не как Python
    callable — для безопасной сериализации в YAML и в DSL-spec.

    Примеры спецификации::

        select: ["id", "amount"]
        filter: "amount > 1000"
        with_columns:
          tax: "amount * 0.2"

    Args:
        select: Колонки для оставления (``None`` — все).
        filter_expr: Polars-выражение фильтрации (`pl.sql_expr`).
        with_columns: Словарь ``new_col -> sql_expr`` для расчётных колонок.
        sort_by: Список колонок для сортировки (опционально).
        descending: Сортировка по убыванию (default ``False``).
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.PURE

    def __init__(
        self,
        *,
        select: list[str] | None = None,
        filter_expr: str | None = None,
        with_columns: dict[str, str] | None = None,
        sort_by: list[str] | None = None,
        descending: bool = False,
        name: str | None = None,
    ) -> None:
        """Сохраняет декларативные параметры запроса."""
        super().__init__(name=name or "polars_query")
        self._select = select
        self._filter = filter_expr
        self._with_columns = with_columns or {}
        self._sort_by = sort_by
        self._descending = descending

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Применяет declarative polars-операции к telu exchange."""
        import polars as pl

        df = _ensure_dataframe(exchange.in_message.body)
        if self._filter:
            df = df.filter(pl.sql_expr(self._filter))
        if self._with_columns:
            df = df.with_columns(
                [
                    pl.sql_expr(expr).alias(col)
                    for col, expr in self._with_columns.items()
                ]
            )
        if self._select:
            df = df.select(self._select)
        if self._sort_by:
            df = df.sort(self._sort_by, descending=self._descending)
        exchange.in_message.body = df.to_dicts()

    def to_spec(self) -> dict[str, Any]:
        """YAML-spec round-trip."""
        spec: dict[str, Any] = {}
        if self._select:
            spec["select"] = list(self._select)
        if self._filter:
            spec["filter"] = self._filter
        if self._with_columns:
            spec["with_columns"] = dict(self._with_columns)
        if self._sort_by:
            spec["sort_by"] = list(self._sort_by)
            spec["descending"] = self._descending
        return {"polars_query": spec}


class PolarsJoinProcessor(BaseProcessor):
    """Wave 7.2 — join body с другим DataFrame.

    Второй источник передаётся через ``other_path`` — точечный путь в
    exchange.headers / context.properties (например, ``headers.lookup_data``).

    Args:
        other_path: Путь к таблице-партнёру (header-key или dotted-path).
        on: Колонки для join (одна или список).
        how: Стратегия join (``inner`` / ``left`` / ``outer`` / ...).
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.PURE

    def __init__(
        self,
        *,
        other_path: str,
        on: str | list[str],
        how: JoinHow = "inner",
        name: str | None = None,
    ) -> None:
        """Запоминает параметры join."""
        super().__init__(name=name or f"polars_join({how})")
        self._other_path = other_path
        self._on = on
        self._how = how

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Выполняет join body с DataFrame по ``other_path``."""
        left = _ensure_dataframe(exchange.in_message.body)
        right_raw = self._resolve_right(exchange)
        right = _ensure_dataframe(right_raw)
        joined = left.join(right, on=self._on, how=self._how)
        exchange.in_message.body = joined.to_dicts()

    def _resolve_right(self, exchange: Exchange[Any]) -> Any:
        """Достаёт правую таблицу из header / context по ``other_path``."""
        node: Any = dict(exchange.in_message.headers or {})
        for part in self._other_path.split("."):
            if not isinstance(node, dict):
                raise ValueError(
                    f"PolarsJoin: путь {self._other_path!r} прерван на {part!r}"
                )
            node = node.get(part)
            if node is None:
                raise ValueError(
                    f"PolarsJoin: пустой right в headers по пути {self._other_path!r}"
                )
        return node

    def to_spec(self) -> dict[str, Any]:
        """YAML-spec round-trip."""
        return {
            "polars_join": {
                "other_path": self._other_path,
                "on": self._on,
                "how": self._how,
            }
        }


class PolarsAggregateProcessor(BaseProcessor):
    """Wave 7.2 — group_by + агрегаты.

    Args:
        group_by: Колонки группировки (одна или список).
        aggregations: ``alias -> agg_expr`` (например, ``{"total": "sum(amount)"}``).
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.PURE

    def __init__(
        self,
        *,
        group_by: str | list[str],
        aggregations: dict[str, str],
        name: str | None = None,
    ) -> None:
        """Сохраняет параметры группировки."""
        super().__init__(name=name or "polars_aggregate")
        self._group_by = [group_by] if isinstance(group_by, str) else list(group_by)
        self._aggs = dict(aggregations)

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Применяет group_by + agg к body."""
        import polars as pl

        df = _ensure_dataframe(exchange.in_message.body)
        agg_exprs = [
            pl.sql_expr(expr).alias(alias) for alias, expr in self._aggs.items()
        ]
        result = df.group_by(self._group_by).agg(agg_exprs)
        exchange.in_message.body = result.to_dicts()

    def to_spec(self) -> dict[str, Any]:
        """YAML-spec round-trip."""
        return {
            "polars_aggregate": {
                "group_by": self._group_by,
                "aggregations": dict(self._aggs),
            }
        }


class PolarsPivotProcessor(BaseProcessor):
    """Wave 7.2 — pivot-таблица.

    Args:
        index: Колонки индекса (строки).
        columns: Колонка, чьи значения становятся новыми колонками.
        values: Колонка с агрегированным значением.
        aggregate_function: Агрегат-функция (``"sum"`` / ``"mean"`` / ...).
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.PURE

    def __init__(
        self,
        *,
        index: str | list[str],
        columns: str,
        values: str,
        aggregate_function: str = "sum",
        name: str | None = None,
    ) -> None:
        """Сохраняет параметры pivot."""
        super().__init__(name=name or "polars_pivot")
        self._index = [index] if isinstance(index, str) else list(index)
        self._columns = columns
        self._values = values
        self._agg = aggregate_function

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Делает pivot-таблицу и сохраняет результат в body."""
        df = _ensure_dataframe(exchange.in_message.body)
        result = df.pivot(
            index=self._index,
            on=self._columns,
            values=self._values,
            aggregate_function=self._agg,
        )
        exchange.in_message.body = result.to_dicts()

    def to_spec(self) -> dict[str, Any]:
        """YAML-spec round-trip."""
        return {
            "polars_pivot": {
                "index": self._index,
                "columns": self._columns,
                "values": self._values,
                "aggregate_function": self._agg,
            }
        }


class PolarsWindowProcessor(BaseProcessor):
    """Wave 7.2 — window-функции (rank / cumsum / lag / ...).

    Применяет агрегат по window'у (``partition_by``, опц. ``order_by``)
    как новую колонку.

    Args:
        partition_by: Колонки разбиения окна.
        order_by: Опциональный список колонок для упорядочивания внутри окна.
        windowed_columns: ``new_col -> sql_expr`` (например,
            ``{"rank": "rank()"}`` или ``{"running_total": "sum(amount)"}``).
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.PURE

    def __init__(
        self,
        *,
        partition_by: str | list[str],
        windowed_columns: dict[str, str],
        order_by: list[str] | None = None,
        name: str | None = None,
    ) -> None:
        """Запоминает параметры window-операций."""
        super().__init__(name=name or "polars_window")
        self._partition = (
            [partition_by] if isinstance(partition_by, str) else list(partition_by)
        )
        self._order = order_by
        self._cols = dict(windowed_columns)

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Применяет window-агрегаты как новые колонки."""
        import polars as pl

        df = _ensure_dataframe(exchange.in_message.body)
        if self._order:
            df = df.sort(self._order)

        new_cols = [
            pl.sql_expr(expr).over(self._partition).alias(alias)
            for alias, expr in self._cols.items()
        ]
        result = df.with_columns(new_cols)
        exchange.in_message.body = result.to_dicts()

    def to_spec(self) -> dict[str, Any]:
        """YAML-spec round-trip."""
        spec: dict[str, Any] = {
            "partition_by": self._partition,
            "windowed_columns": dict(self._cols),
        }
        if self._order:
            spec["order_by"] = list(self._order)
        return {"polars_window": spec}
