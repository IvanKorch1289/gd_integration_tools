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


def _final_froms(stmt: Any) -> list[Any]:
    """Список FROM-элементов запроса с учётом перехода SQLAlchemy 1.4→2.0.

    ``Select.froms`` помечен deprecated (SADeprecationWarning, удаляется),
    ``Select.get_final_froms()`` — актуальный API.

    Args:
        stmt: SQLAlchemy statement.

    Returns:
        Список FROM-элементов (пустой для DML).
    """
    getter = getattr(stmt, "get_final_froms", None)
    if callable(getter):
        return list(getter())
    return list(getattr(stmt, "froms", []))


def _tenant_aware_entities(stmt: Any) -> list[Any]:
    """Найти tenant-aware сущности, участвующие в запросе.

    Две стратегии (аудит 2026-10-01, F-AM):

    1. ``statement.column_descriptions`` — точная сущность SELECT-запроса.
       Единственный надёжный источник для ``join``: у ``_ORMJoin`` атрибут
       ``entity_namespace`` — коллекция колонок, а не класс, поэтому прежний
       обход ``stmt.froms`` **молча не фильтровал join-запросы** (кросс-tenant
       чтение воспроизведено на ``select(Order, User.id).join(...)``);
    2. ``statement.entity_description`` — сущность ORM ``UPDATE``/``DELETE``
       (у DML нет ни ``column_descriptions``, ни ``froms``);
    3. откат на ``stmt.froms`` для запросов без column-описаний
       (например ``select(func.count()).select_from(Order)``).

    Args:
        stmt: SQLAlchemy statement.

    Returns:
        Список tenant-aware mapped-классов (может быть пустым).
    """
    entities: list[Any] = []
    for description in getattr(stmt, "column_descriptions", None) or []:
        entity = description.get("entity") if isinstance(description, dict) else None
        if entity is not None and _is_tenant_aware(entity):
            entities.append(entity)
    if entities:
        return entities

    dml_description = getattr(stmt, "entity_description", None)
    if isinstance(dml_description, dict):
        dml_entity = dml_description.get("entity")
        if dml_entity is not None and _is_tenant_aware(dml_entity):
            return [dml_entity]

    for frm in _final_froms(stmt):
        entity = getattr(frm, "entity_namespace", None)
        if entity and _is_tenant_aware(entity):
            entities.append(entity)
    return entities


def apply_tenant_filter(_target: Any = None) -> None:
    """Регистрирует SQLAlchemy event listeners для tenant isolation.

    * ``do_orm_execute`` → auto-filter **SELECT, UPDATE и DELETE** по ``tenant_id``
      (S88 W2: це Session event). До F-AM DML отсекался условием
      ``if not is_select: return``, из-за чего ``repository.update()`` и
      ``repository.delete()`` меняли чужой tenant (воспроизведено: 1 строка).
    * ``before_flush`` → auto-set ``tenant_id`` на new objects.

    Фильтруются **все** tenant-aware сущности запроса, а не только первая:
    join двух tenant-aware таблиц иначе оставлял вторую неограниченной.

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
        if not (
            orm_execute_state.is_select
            or orm_execute_state.is_update
            or orm_execute_state.is_delete
        ):
            return

        tenant_id = get_tenant_id()
        if not tenant_id:
            return

        stmt = orm_execute_state.statement
        for entity in _tenant_aware_entities(stmt):
            stmt = stmt.where(entity.tenant_id == tenant_id)
        orm_execute_state.statement = stmt

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
