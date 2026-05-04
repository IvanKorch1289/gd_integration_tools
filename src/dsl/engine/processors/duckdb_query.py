"""Wave 7.3 — DuckDB DSL-процессор для аналитических SQL-запросов.

Мотивация: DuckDB — embedded analytical SQL engine (как SQLite, но с
columnar-storage и vectorized executor). Идеален для in-process сложных
SQL над body / lookup-таблицами без поднятия отдельного БД-сервера.

Контракт:

* Источники (``sources``) — словарь ``alias -> rows``, где rows: ``list[dict]``.
* Body также автоматически регистрируется как алиас ``body`` (если есть).
* SQL — стандартный DuckDB SQL (поддерживает CTE, оконные функции,
  qualify, list-агрегаты — см. https://duckdb.org/docs/sql/introduction).

DuckDB соединение — in-process (default). Опция ``persistent_path``
открывает файл-БД (с auto-checkpoint).

Все процессоры — pure-аналитика (``side_effect=PURE``).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, ClassVar

from src.core.types.side_effect import SideEffectKind
from src.dsl.engine.processors.base import BaseProcessor

if TYPE_CHECKING:
    from src.dsl.engine.context import ExecutionContext
    from src.dsl.engine.exchange import Exchange

__all__ = ("DuckDbQueryProcessor",)

_logger = logging.getLogger("dsl.duckdb")


class DuckDbQueryProcessor(BaseProcessor):
    """Wave 7.3 — выполнение DuckDB-SQL над body + lookup-таблицами.

    Args:
        sql: SQL-запрос (ссылается на алиасы ``body`` и ``sources.*``).
        sources: Словарь ``alias -> dotted_path_in_headers`` для
            привязки lookup-таблиц из ``exchange.headers``. Например,
            ``{"customers": "lookup.customers", "orders": "lookup.orders"}``.
        persistent_path: Путь к файлу DuckDB-БД (опц). По умолчанию —
            in-memory (быстро, но без persistence между запусками).

    Пример::

        builder.duckdb_query(
            sql='''
                SELECT b.id, b.amount, c.name AS customer_name
                FROM body b
                LEFT JOIN customers c ON c.id = b.customer_id
                WHERE b.amount > 1000
            ''',
            sources={"customers": "lookup.customers"},
        )
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.PURE

    def __init__(
        self,
        *,
        sql: str,
        sources: dict[str, str] | None = None,
        persistent_path: str | None = None,
        name: str | None = None,
    ) -> None:
        """Сохраняет параметры запроса."""
        super().__init__(name=name or "duckdb_query")
        if not sql or not sql.strip():
            raise ValueError("DuckDbQueryProcessor: пустой SQL")
        self._sql = sql
        self._sources = dict(sources or {})
        self._persistent_path = persistent_path

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Выполняет SQL и кладёт результат в body как list[dict]."""
        try:
            import duckdb
        except ImportError:
            raise RuntimeError("duckdb не установлен — добавьте в зависимости проекта")

        conn = (
            duckdb.connect(self._persistent_path)
            if self._persistent_path
            else duckdb.connect(":memory:")
        )
        try:
            self._register_body(conn, exchange.in_message.body)
            self._register_sources(conn, exchange)
            result = conn.execute(self._sql).fetch_arrow_table()
            exchange.in_message.body = self._arrow_to_rows(result)
        finally:
            conn.close()

    @staticmethod
    def _register_body(conn: Any, body: Any) -> None:
        """Регистрирует ``body`` как DuckDB-таблицу ``body``."""
        if body is None:
            return
        rows = body if isinstance(body, list) else [body]
        if not rows:
            return
        conn.register("body", _rows_to_arrow(rows))

    def _register_sources(self, conn: Any, exchange: Exchange[Any]) -> None:
        """Регистрирует source-таблицы из ``exchange.in_message.headers``."""
        for alias, path in self._sources.items():
            data = _follow_path(dict(exchange.in_message.headers or {}), path)
            if data is None:
                _logger.debug(
                    "DuckDbQuery: source %r по пути %r отсутствует — алиас не зарегистрирован",
                    alias,
                    path,
                )
                continue
            rows = data if isinstance(data, list) else [data]
            if rows:
                conn.register(alias, _rows_to_arrow(rows))

    @staticmethod
    def _arrow_to_rows(arrow_table: Any) -> list[dict[str, Any]]:
        """pyarrow.Table → list[dict]."""
        return arrow_table.to_pylist()

    def to_spec(self) -> dict[str, Any]:
        """YAML-spec round-trip."""
        spec: dict[str, Any] = {"sql": self._sql}
        if self._sources:
            spec["sources"] = dict(self._sources)
        if self._persistent_path:
            spec["persistent_path"] = self._persistent_path
        return {"duckdb_query": spec}


def _follow_path(node: Any, path: str) -> Any:
    """Извлекает значение по точечному пути."""
    for part in path.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
        if node is None:
            return None
    return node


def _rows_to_arrow(rows: list[dict[str, Any]]) -> Any:
    """Преобразует list[dict] в pyarrow.Table (требуется DuckDB ``register``)."""
    import pyarrow as pa

    return pa.Table.from_pylist(rows)
