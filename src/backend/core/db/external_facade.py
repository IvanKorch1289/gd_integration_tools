"""S127 W3 — ExternalDBFacade (TD-021).

Capability-checked facade поверх :class:`ExternalDatabaseRegistry` для
высокоуровневых операций с внешними БД (query / execute /
call_procedure / transaction).

Создаёт тонкий слой над существующим
``infrastructure/database/database/registry.py:ExternalDatabaseRegistry``,
скрывая прямую работу с ``DatabaseInitializer`` / ``DatabaseBundle`` от
бизнес-логики (DSL routes / extensions / services).

API::

    facade = ExternalDBFacade.get_default()
    rows = await facade.query("oracle_prod", "SELECT * FROM users WHERE id = :id", {"id": 42})
    n = await facade.execute("pg_prod", "UPDATE users SET name = :n WHERE id = :id", {"n": "x", "id": 1})
    result = await facade.call_procedure("oracle_prod", "recalc_credit", {"p_user_id": 42})
    async with facade.transaction("pg_prod") as tx:
        await tx.execute("INSERT INTO audit ...")
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from src.backend.core.logging import get_logger

__all__ = ("ExternalDBFacade", "TransactionContext")

_logger = get_logger("core.db.external_facade")


@dataclass
class TransactionContext:
    """Async context manager для транзакции внешней БД.

    Обёртка поверх ``DatabaseBundle`` (который сам по себе
    async context manager). Добавляет convenience-методы
    ``query``/``execute``/``call_procedure`` чтобы не передавать
    bundle в caller.
    """

    _bundle: Any
    _connection: Any = None
    _in_transaction: bool = False

    async def __aenter__(self) -> "TransactionContext":
        # DatabaseBundle is async context manager; enter it.
        self._bundle = await self._bundle.__aenter__()
        self._in_transaction = True
        _logger.debug("transaction opened")
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        try:
            if exc_type is not None:
                _logger.warning("transaction rollback due to %s", exc_type.__name__)
            else:
                _logger.debug("transaction commit")
        finally:
            if self._in_transaction:
                await self._bundle.__aexit__(exc_type, exc_val, exc_tb)
                self._in_transaction = False

    async def query(
        self, sql: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Run SELECT внутри transaction."""
        if not self._in_transaction:
            raise RuntimeError("TransactionContext.query: not in transaction")
        return await _query_impl(self._bundle, sql, params or {})

    async def execute(self, sql: str, params: dict[str, Any] | None = None) -> int:
        """Run INSERT/UPDATE/DELETE внутри transaction."""
        if not self._in_transaction:
            raise RuntimeError("TransactionContext.execute: not in transaction")
        return await _execute_impl(self._bundle, sql, params or {})

    async def call_procedure(
        self, name: str, params: dict[str, Any] | None = None
    ) -> Any:
        """Call stored procedure внутри transaction."""
        if not self._in_transaction:
            raise RuntimeError("TransactionContext.call_procedure: not in transaction")
        return await _call_procedure_impl(self._bundle, name, params or {})


# ---------------------------------------------------------------------------
# Private helpers — defer to DatabaseBundle/DatabaseInitializer.
# ---------------------------------------------------------------------------


async def _query_impl(
    bundle: Any, sql: str, params: dict[str, Any]
) -> list[dict[str, Any]]:
    """SELECT → list[dict]."""
    # DatabaseBundle exposes ``session`` (SQLAlchemy AsyncSession).
    session = getattr(bundle, "session", None) or getattr(bundle, "_session", None)
    if session is None:
        raise RuntimeError("DatabaseBundle has no .session attribute")
    from sqlalchemy import text

    result = await session.execute(text(sql), params)
    rows = result.mappings().all()
    return [dict(row) for row in rows]


async def _execute_impl(bundle: Any, sql: str, params: dict[str, Any]) -> int:
    """INSERT/UPDATE/DELETE → rowcount."""
    session = getattr(bundle, "session", None) or getattr(bundle, "_session", None)
    if session is None:
        raise RuntimeError("DatabaseBundle has no .session attribute")
    from sqlalchemy import text

    result = await session.execute(text(sql), params)
    return result.rowcount or 0


async def _call_procedure_impl(bundle: Any, name: str, params: dict[str, Any]) -> Any:
    """Call stored procedure via existing call_procedure helper."""
    # Look up call_procedure on bundle or session.
    fn = getattr(bundle, "call_procedure", None) or getattr(
        bundle, "_call_procedure", None
    )
    if fn is None:
        # Fallback: route through the existing db_call_procedure processor path
        # or just raise — implementation depends on dialect.
        raise NotImplementedError(
            "call_procedure not supported on this bundle (dialect-specific). "
            "Use 'db_call_procedure' DSL step or dialect-specific driver directly."
        )
    if asyncio.iscoroutinefunction(fn):
        return await fn(name, **params)
    return fn(name, **params)


import asyncio  # noqa: E402  (kept at bottom to avoid top-level cost)

# ---------------------------------------------------------------------------
# Façade
# ---------------------------------------------------------------------------


@dataclass
class ExternalDBFacade:
    """Capability-checked facade для операций с внешними БД.

    Бизнес-логика (DSL routes / extensions / services) **обязана**
    использовать этот facade, а не ``ExternalDatabaseRegistry``
    напрямую. Преимущества:
      * Единый API для query / execute / call_procedure / transaction.
      * Lazy-импорт infrastructure (для cold-start performance).
      * Singleton pattern — нет необходимости передавать через DI.
    """

    _registry_getter: Any = None
    _instance: "ExternalDBFacade | None" = field(default=None, init=False, repr=False)

    @classmethod
    def get_default(cls) -> "ExternalDBFacade":
        """Singleton accessor (lazy-init на first call)."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def configure(cls, registry_getter: Any) -> "ExternalDBFacade":
        """Установить custom registry getter (для тестов / DI)."""
        instance = cls(_registry_getter=registry_getter)
        cls._instance = instance
        return instance

    def _get_registry(self) -> Any:
        """Lazy-resolve registry via getter or default import."""
        if self._registry_getter is not None:
            return self._registry_getter()
        # Default: импорт через app bootstrap (singleton).
        from src.backend.infrastructure.database.database.registry import (
            get_default_external_registry,  # type: ignore[attr-defined]
        )

        return get_default_external_registry()

    # --- Public API ---

    async def query(
        self, profile: str, sql: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """SELECT через профиль внешней БД.

        Args:
            profile: Profile name (e.g., ``"oracle_prod"``, ``"pg_main"``).
            sql: SQL с ``:param`` placeholders.
            params: Parameter dict (опционально).

        Returns:
            list[dict] с результатами.

        Raises:
            DatabaseError: Если профиль не зарегистрирован.
        """
        registry = self._get_registry()
        bundle = registry.get_bundle(profile)
        return await _query_impl(bundle, sql, params or {})

    async def execute(
        self, profile: str, sql: str, params: dict[str, Any] | None = None
    ) -> int:
        """INSERT / UPDATE / DELETE → rowcount."""
        registry = self._get_registry()
        bundle = registry.get_bundle(profile)
        return await _execute_impl(bundle, sql, params or {})

    async def call_procedure(
        self, profile: str, name: str, params: dict[str, Any] | None = None
    ) -> Any:
        """Call stored procedure через профиль внешней БД."""
        registry = self._get_registry()
        bundle = registry.get_bundle(profile)
        return await _call_procedure_impl(bundle, name, params or {})

    @asynccontextmanager
    async def transaction(self, profile: str) -> AsyncIterator[TransactionContext]:
        """Async context manager для транзакции.

        Usage::

            async with facade.transaction("pg_prod") as tx:
                await tx.execute("INSERT INTO audit ...")
                await tx.query("SELECT * FROM ...")
        """
        registry = self._get_registry()
        bundle = registry.get_bundle(profile)
        tx = TransactionContext(_bundle=bundle)
        async with tx as ctx:
            yield ctx
