"""Типизированный SQL-builder для ClickHouse (S13 K2 W2).

Fluent API c защитой от SQL-injection через параметризацию. Заменяет
raw-SQL запросы в ``services/analytics/`` и DSL audit-шагах.

Usage::

    sql, params = (
        ClickHouseQueryBuilder()
        .select("event_type", "count(*) AS cnt")
        .from_("audit_log")
        .where_between("created_at", "2026-01-01", "2026-12-31")
        .where_in("level", ["ERROR", "CRITICAL"])
        .group_by("event_type")
        .having("cnt > 10")
        .order_by("cnt", desc=True)
        .limit(100)
        .build()
    )
    rows = await client.execute_iter(sql, params=params)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = ("ClickHouseQueryBuilder", "Condition")


@dataclass(frozen=True, slots=True)
class Condition:
    """SQL-условие WHERE/HAVING с параметризацией."""

    expression: str
    params: tuple[Any, ...] = ()

    @classmethod
    def eq(cls, column: str, value: Any) -> Condition:
        """``column = value`` (parametrized)."""
        return cls(f"{column} = %s", (value,))

    @classmethod
    def neq(cls, column: str, value: Any) -> Condition:
        """``column != value`` (parametrized)."""
        return cls(f"{column} != %s", (value,))

    @classmethod
    def gt(cls, column: str, value: Any) -> Condition:
        """``column > value`` (parametrized)."""
        return cls(f"{column} > %s", (value,))

    @classmethod
    def gte(cls, column: str, value: Any) -> Condition:
        """``column >= value`` (parametrized)."""
        return cls(f"{column} >= %s", (value,))

    @classmethod
    def lt(cls, column: str, value: Any) -> Condition:
        """``column < value`` (parametrized)."""
        return cls(f"{column} < %s", (value,))

    @classmethod
    def lte(cls, column: str, value: Any) -> Condition:
        """``column <= value`` (parametrized)."""
        return cls(f"{column} <= %s", (value,))

    @classmethod
    def like(cls, column: str, pattern: str) -> Condition:
        """``column LIKE pattern`` (parametrized; ClickHouse-style %)."""
        return cls(f"{column} LIKE %s", (pattern,))

    @classmethod
    def raw(cls, expression: str, *params: Any) -> Condition:
        """Raw SQL expression with params (escape hatch for custom operators).

        Args:
            expression: Raw SQL fragment (e.g., ``"toDate(ts) = %s"``).
            *params: Bind params (any type).

        Returns:
            :class:`Condition` with raw expression.
        """
        return cls(expression, tuple(params))


@dataclass
class ClickHouseQueryBuilder:
    """Fluent builder для SELECT-запросов в ClickHouse."""

    _select: list[str] = field(default_factory=list)
    _distinct: bool = False
    _from: str | None = None
    _from_alias: str | None = None
    _ctes: list[tuple[str, ClickHouseQueryBuilder | str]] = field(default_factory=list)
    _wheres: list[Condition] = field(default_factory=list)
    _group_by: list[str] = field(default_factory=list)
    _havings: list[Condition] = field(default_factory=list)
    _order_by: list[tuple[str, bool]] = field(default_factory=list)
    _limit: int | None = None
    _offset: int = 0
    _final: bool = False
    _sample: float | None = None

    def select(self, *cols: str, distinct: bool = False) -> ClickHouseQueryBuilder:
        """Добавить columns в SELECT. ``distinct=True`` добавляет DISTINCT."""
        self._select.extend(cols)
        if distinct:
            self._distinct = True
        return self

    def from_(self, table: str, alias: str | None = None) -> ClickHouseQueryBuilder:
        """FROM clause: ``FROM <table> [AS <alias>]``."""
        self._from = table
        self._from_alias = alias
        return self

    def with_cte(
        self, name: str, query: ClickHouseQueryBuilder | str
    ) -> ClickHouseQueryBuilder:
        """WITH clause: добавить CTE ``name AS <query>``."""
        self._ctes.append((name, query))
        return self

    def where(self, *conditions: Condition) -> ClickHouseQueryBuilder:
        """WHERE clause: добавить AND-ed conditions."""
        self._wheres.extend(conditions)
        return self

    def where_in(self, col: str, values: list[Any]) -> ClickHouseQueryBuilder:
        """WHERE IN clause with parametrized values.

        Args:
            col: Column name.
            values: List of values.

        Returns:
            Self for chaining.
        """
        if not values:
            # WHERE col IN () — заведомо false; используем 1=0.
            self._wheres.append(Condition("1=0", ()))
            return self
        placeholders = ", ".join("%s" for _ in values)
        self._wheres.append(Condition(f"{col} IN ({placeholders})", tuple(values)))
        return self

    def where_between(self, col: str, start: Any, end: Any) -> ClickHouseQueryBuilder:
        """WHERE BETWEEN clause with parametrized values.

        Args:
            col: Column name.
            start: Range start.
            end: Range end.

        Returns:
            Self for chaining.
        """
        self._wheres.append(Condition(f"{col} BETWEEN %s AND %s", (start, end)))
        return self

    def group_by(self, *cols: str) -> ClickHouseQueryBuilder:
        """GROUP BY clause.

        Args:
            cols: Columns to group by.

        Returns:
            Self for chaining.
        """
        self._group_by.extend(cols)
        return self

    def having(self, *conditions: Condition | str) -> ClickHouseQueryBuilder:
        """HAVING clause.

        Args:
            conditions: Conditions to apply.

        Returns:
            Self for chaining.
        """
        for c in conditions:
            if isinstance(c, str):
                self._havings.append(Condition(c, ()))
            else:
                self._havings.append(c)
        return self

    def order_by(self, *cols: str, desc: bool = False) -> ClickHouseQueryBuilder:
        """ORDER BY clause.

        Args:
            cols: Columns to order by.
            desc: Descending order.

        Returns:
            Self for chaining.
        """
        for c in cols:
            self._order_by.append((c, desc))
        return self

    def limit(self, n: int, offset: int = 0) -> ClickHouseQueryBuilder:
        """LIMIT clause.

        Args:
            n: Maximum rows.
            offset: Rows offset.

        Returns:
            Self for chaining.
        """
        self._limit = n
        self._offset = offset
        return self

    def final(self, materialize_views: bool = True) -> ClickHouseQueryBuilder:
        """ClickHouse-специфичный FINAL модификатор."""
        self._final = materialize_views
        return self

    def sample(self, rate: float) -> ClickHouseQueryBuilder:
        """SAMPLE-модификатор для ускорения approximate-запросов."""
        if not 0.0 < rate <= 1.0:
            raise ValueError("sample rate must be in (0.0, 1.0]")
        self._sample = rate
        return self

    def build(self) -> tuple[str, list[Any]]:
        """Собирает SQL + params.

        Returns:
            (sql, params) tuple. ``params`` — позиционные значения для
            ``client.execute(sql, params=params)``.
        """
        if not self._from:
            raise ValueError("FROM clause is required")
        if not self._select:
            raise ValueError("SELECT clause is required")

        sql_parts: list[str] = []
        params: list[Any] = []

        if self._ctes:
            cte_parts: list[str] = []
            for name, q in self._ctes:
                if isinstance(q, ClickHouseQueryBuilder):
                    inner_sql, inner_params = q.build()
                    cte_parts.append(f"{name} AS ({inner_sql})")
                    params.extend(inner_params)
                else:
                    cte_parts.append(f"{name} AS ({q})")
            sql_parts.append("WITH " + ", ".join(cte_parts))

        distinct_kw = "DISTINCT " if self._distinct else ""
        sql_parts.append(f"SELECT {distinct_kw}{', '.join(self._select)}")
        from_clause = self._from
        if self._from_alias:
            from_clause = f"{self._from} AS {self._from_alias}"
        if self._final:
            from_clause = f"{from_clause} FINAL"
        if self._sample is not None:
            from_clause = f"{from_clause} SAMPLE {self._sample}"
        sql_parts.append(f"FROM {from_clause}")

        if self._wheres:
            where_str = " AND ".join(c.expression for c in self._wheres)
            sql_parts.append(f"WHERE {where_str}")
            for c in self._wheres:
                params.extend(c.params)

        if self._group_by:
            sql_parts.append(f"GROUP BY {', '.join(self._group_by)}")

        if self._havings:
            having_str = " AND ".join(c.expression for c in self._havings)
            sql_parts.append(f"HAVING {having_str}")
            for c in self._havings:
                params.extend(c.params)

        if self._order_by:
            order_parts = [
                f"{col} {'DESC' if desc else 'ASC'}" for col, desc in self._order_by
            ]
            sql_parts.append(f"ORDER BY {', '.join(order_parts)}")

        if self._limit is not None:
            if self._offset:
                sql_parts.append(f"LIMIT {self._offset}, {self._limit}")
            else:
                sql_parts.append(f"LIMIT {self._limit}")

        return " ".join(sql_parts), params

    async def execute(self, client: Any) -> list[dict[str, Any]]:
        """Выполняет запрос на ClickHouse client.

        Args:
            client: объект с ``execute(sql, params=...)`` методом
                (например, ClickHouseClient или clickhouse-connect AsyncClient).
        """
        sql, params = self.build()
        # ClickHouse params формат: %(name)s — но мы используем %s; передаём кортежем.
        return await client.execute(sql, params=params)
