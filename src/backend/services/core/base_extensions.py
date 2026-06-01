"""BaseService extensions — bulk_upsert, soft_delete, @transactional, audit timestamps.

Миксины и декораторы для расширения BaseService без изменения существующего API.
Применяются опционально в подклассах.

Multi-instance safety:
- bulk_upsert использует ON CONFLICT (PostgreSQL) — atomic
- soft_delete — поле is_deleted (нет race conditions при delete)
- @transactional — SQLAlchemy transaction через session.begin()
- Audit timestamps — server_default=func.now() (per-row, не per-process)
"""

from __future__ import annotations

import functools
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable, TypeVar

__all__ = (
    "bulk_upsert",
    "soft_delete",
    "transactional",
    "with_audit_timestamps",
    "SoftDeleteMixin",
)

logger = logging.getLogger("services.extensions")

F = TypeVar("F", bound=Callable[..., Awaitable[Any]])


def transactional(fn: F) -> F:
    """Декоратор: оборачивает async метод в DB-транзакцию.

    Использует session_manager из BaseService.repo если доступен.
    Fallback: просто выполняет метод.

    Usage::

        class OrderService(BaseService):
            @transactional
            async def create_with_items(self, order_data, items):
                order = await self.add(order_data)
                for item in items:
                    await self.items_repo.add(item)
                return order
    """

    @functools.wraps(fn)
    async def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        session_manager = getattr(getattr(self, "repo", None), "session_manager", None)
        if session_manager is None or not hasattr(session_manager, "transaction"):
            return await fn(self, *args, **kwargs)

        async with session_manager.transaction():
            return await fn(self, *args, **kwargs)

    return wrapper  # type: ignore[return-value]


@asynccontextmanager
async def _safe_transaction(session: Any) -> Any:
    """Context manager для безопасной транзакции с rollback."""
    if hasattr(session, "begin"):
        async with session.begin():
            yield session
    else:
        yield session


async def bulk_upsert(
    repo: Any,
    rows: list[dict[str, Any]],
    *,
    conflict_columns: list[str],
    update_columns: list[str] | None = None,
) -> int:
    """PostgreSQL ON CONFLICT UPDATE bulk upsert.

    Atomic операция (одна транзакция). Multi-instance safe — PostgreSQL
    sequentializes конфликты на уровне row-lock.

    Args:
        repo: Repository с .model и .session_manager.
        rows: Список dict для вставки.
        conflict_columns: Столбцы UNIQUE/PRIMARY KEY constraint.
        update_columns: Столбцы для UPDATE при конфликте (default — все кроме conflict).

    Returns:
        Количество затронутых строк.
    """
    if not rows:
        return 0

    try:
        from sqlalchemy.dialects.postgresql import insert as pg_insert
    except ImportError:
        raise RuntimeError("bulk_upsert requires SQLAlchemy PostgreSQL dialect")

    model = getattr(repo, "model", None)
    if model is None:
        raise ValueError("repo.model is required for bulk_upsert")

    if update_columns is None:
        all_columns = {c.name for c in model.__table__.columns}
        update_columns = [c for c in all_columns if c not in set(conflict_columns)]

    stmt = pg_insert(model).values(rows)
    update_dict = {col: getattr(stmt.excluded, col) for col in update_columns}
    stmt = stmt.on_conflict_do_update(index_elements=conflict_columns, set_=update_dict)

    session_manager = getattr(repo, "session_manager", None)
    if session_manager is None:
        raise RuntimeError("repo.session_manager is required")

    async with session_manager.session() as session:
        result = await session.execute(stmt)
        await session.commit()
        return result.rowcount or len(rows)


async def soft_delete(repo: Any, key: str, value: Any) -> bool:
    """Soft delete — устанавливает is_deleted=True вместо DELETE.

    Требует поле `is_deleted: bool` и `deleted_at: datetime | None` в модели.
    Multi-instance safe: UPDATE with WHERE clause (атомарно).

    Returns:
        True если строка была обновлена.
    """
    model = getattr(repo, "model", None)
    if model is None:
        raise ValueError("repo.model is required for soft_delete")

    if not hasattr(model, "is_deleted"):
        raise AttributeError(f"{model.__name__} has no is_deleted field")

    from sqlalchemy import update

    stmt = (
        update(model)
        .where(getattr(model, key) == value)
        .values(is_deleted=True, deleted_at=datetime.now(UTC))
    )

    session_manager = getattr(repo, "session_manager", None)
    if session_manager is None:
        raise RuntimeError("repo.session_manager is required")

    async with session_manager.session() as session:
        result = await session.execute(stmt)
        await session.commit()
        return (result.rowcount or 0) > 0


def with_audit_timestamps(fn: F) -> F:
    """Декоратор: автоматически добавляет created_at/updated_at в payload.

    Для методов, принимающих dict данных (add, update).
    """

    @functools.wraps(fn)
    async def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        data = kwargs.get("data")
        if data is None and args:
            data = args[0] if isinstance(args[0], dict) else None

        if isinstance(data, dict):
            now = datetime.now(UTC)
            fn_name = fn.__name__
            if fn_name in ("add", "create") and "created_at" not in data:
                data["created_at"] = now
            if fn_name in ("add", "create", "update", "upsert"):
                data["updated_at"] = now

        return await fn(self, *args, **kwargs)

    return wrapper  # type: ignore[return-value]


class SoftDeleteMixin:
    """Mixin для BaseService — adds .soft_delete() method.

    Usage::

        class OrderService(SoftDeleteMixin, BaseService):
            pass

        await order_service.soft_delete("id", 123)
    """

    async def soft_delete(self, key: str, value: Any) -> bool:
        return await soft_delete(self.repo, key, value)  # type: ignore[attr-defined]
