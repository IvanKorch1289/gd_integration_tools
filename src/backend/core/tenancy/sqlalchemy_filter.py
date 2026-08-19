"""S107 W1 — ``core/tenancy/sqlalchemy_filter``: row-level tenant isolation.

Multi-tenancy mixin + SQLAlchemy event listener для auto-filter queries
по ``tenant_id``. Перемещено из
:mod:`src.backend.infrastructure.database.tenant_filter` (S107 W1,
TD-002 residual) для устранения layer violation: domain models
импортировали ``TenantMixin`` из ``infrastructure/``, что нарушает
V22 layer policy (extensions/core должны импортировать ТОЛЬКО
``core/`` + capability-checked фасады).

S88 W2 (V2 P0 #6): FIXED — wire на Session class (``do_orm_execute``
event), не на sessionmaker.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import String, event
from sqlalchemy.orm import Mapped, Session, mapped_column

from src.backend.core.tenancy import get_tenant_id

__all__ = ("TenantMixin", "apply_tenant_filter")


class TenantMixin:
    """Mixin для моделей, поддерживающих multi-tenancy.

    Добавляет колонку ``tenant_id`` + автоматическую фильтрацию
    (через ``apply_tenant_filter``).

    Usage::

        class Order(TenantMixin, BaseModel):
            ...
    """

    tenant_id: Mapped[str] = mapped_column(
        String(64), index=True, nullable=False, default="default"
    )


_INSTALLED: bool = False


def _is_tenant_aware(entity: Any) -> bool:
    """Check if mapped entity has ``tenant_id`` column (TenantMixin applied)."""
    return hasattr(entity, "tenant_id")


def apply_tenant_filter(_target: Any = None) -> None:
    """Регистрирует SQLAlchemy event listeners для tenant isolation.

    * ``do_orm_execute`` → auto-filter SELECT по ``tenant_id``
      (S88 W2: це Session event).
    * ``before_flush`` → auto-set ``tenant_id`` на new objects.

    Ідемпотентно: повторний виклик — no-op.

    NOTE: аргумент ``_target`` збережено для backward compat с
    оригінальним API, но фактически listeners реєструються на класі
    ``Session`` (SessionEvents), оскільки ``do_orm_execute`` не існує
    ні на Engine, ні на sessionmaker.
    """
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    @event.listens_for(Session, "do_orm_execute")
    def _filter_by_tenant(orm_execute_state: Any) -> None:
        if not orm_execute_state.is_select:
            return

        tenant_id = get_tenant_id()
        if not tenant_id:
            return

        stmt = orm_execute_state.statement
        for frm in getattr(stmt, "froms", []):
            entity = getattr(frm, "entity_namespace", None)
            if entity and _is_tenant_aware(entity):
                stmt = stmt.where(entity.tenant_id == tenant_id)
                orm_execute_state.statement = stmt
                break

    @event.listens_for(Session, "before_flush")
    def _set_tenant_on_new(
        session: Session, _flush_context: Any, _instances: Any
    ) -> None:
        tenant_id = get_tenant_id()
        if not tenant_id:
            return

        for obj in session.new:
            if hasattr(obj, "tenant_id") and not obj.tenant_id:
                obj.tenant_id = tenant_id
