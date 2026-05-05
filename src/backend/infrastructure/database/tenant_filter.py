"""Row-level tenant isolation — auto-filter queries по tenant_id."""

from __future__ import annotations

from typing import Any

from sqlalchemy import String, event
from sqlalchemy.orm import Mapped, Session, mapped_column

from src.infrastructure.observability.correlation import get_tenant_id

__all__ = ("TenantMixin", "apply_tenant_filter")


class TenantMixin:
    """Mixin для моделей, поддерживающих multi-tenancy.

    Добавляет колонку tenant_id + автоматическую фильтрацию.

    Usage:
        class Order(TenantMixin, BaseModel):
            ...
    """

    tenant_id: Mapped[str] = mapped_column(
        String(64), index=True, nullable=False, default="default"
    )


def _is_tenant_aware(mapper: Any) -> bool:
    return hasattr(mapper.class_, "tenant_id") and "tenant_id" in [
        c.key for c in mapper.columns
    ]


def apply_tenant_filter(session_factory: Any) -> None:
    """Регистрирует SQLAlchemy event listeners для tenant isolation.

    - Before flush: auto-set tenant_id на новых объектах
    - After do_orm_execute: auto-filter SELECT по tenant_id
    """

    @event.listens_for(session_factory, "do_orm_execute")
    def _filter_by_tenant(orm_execute_state: Any) -> None:
        if not orm_execute_state.is_select:
            return

        tenant_id = get_tenant_id()
        if not tenant_id:
            return

        stmt = orm_execute_state.statement
        for frm in getattr(stmt, "froms", []):
            entity = getattr(frm, "entity_namespace", None)
            if entity and hasattr(entity, "tenant_id"):
                stmt = stmt.where(entity.tenant_id == tenant_id)
                orm_execute_state.statement = stmt
                break

    @event.listens_for(session_factory, "before_flush")
    def _set_tenant_on_new(
        session: Session, _flush_context: Any, instances: Any
    ) -> None:
        tenant_id = get_tenant_id()
        if not tenant_id:
            return

        for obj in session.new:
            if hasattr(obj, "tenant_id") and not obj.tenant_id:
                obj.tenant_id = tenant_id
