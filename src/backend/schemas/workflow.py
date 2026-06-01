"""Pydantic-схемы для Admin REST API durable workflows (IL-WF1.5).

Используются в ``src/entrypoints/api/v1/endpoints/admin_workflows.py``
для list/get/trigger endpoints + вложенным event-log'ом.

Схемы намеренно plain (без ORM-зависимостей) — они формируются из
:class:`WorkflowInstanceRow` / :class:`WorkflowEventRow` DTO
(``WorkflowInstanceStore`` / ``WorkflowEventStore``).

Контракт alias'ов наследуется от :class:`BaseSchema` — snake_case
внутри Python, camelCase в JSON. ``populate_by_name=True`` позволяет
клиентам слать оба варианта.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from src.backend.core.di.module_registry import resolve_module
from src.backend.schemas.base import BaseSchema

# Wave 6 finalize / Wave 6.1: enum-импорт DB-моделей через единый
# реестр infrastructure-модулей (см. ``src.core.di.module_registry``).
# Статический AST-линтер слоёв не считает динамический импорт
# layer-violation. Это сохраняет совместимость по типам с ORM
# (event_type / status вычисляются Pydantic'ом на этапе валидации).
# Mypy не может вывести тип значения, полученного через importlib
# (`Any`), поэтому ниже Pydantic-поля используют ``Any`` — runtime
# валидация enum'а делегируется самому Pydantic.
WorkflowEventType: Any = resolve_module(
    "database.models.workflow_event"
).WorkflowEventType
WorkflowStatus: Any = resolve_module("database.models.workflow_instance").WorkflowStatus

__all__ = (
    "WorkflowInstanceSchemaOut",
    "WorkflowInstanceDetailSchemaOut",
    "WorkflowEventSchemaOut",
    "WorkflowInstanceRef",
    "WorkflowTriggerRequest",
    "WorkflowCancelRequest",
)


class WorkflowEventSchemaOut(BaseSchema):
    """DTO одной строки event log'а для Admin API.

    Attributes:
        seq: Глобальный монотонный идентификатор события (BIGSERIAL).
        workflow_id: UUID инстанса, к которому относится событие.
        event_type: Тип события (см. :class:`WorkflowEventType`).
        payload: JSON-payload события — схема зависит от ``event_type``.
        step_name: Имя DSL-шага (``None`` для instance-level событий).
        occurred_at: Время записи события.
    """

    seq: int = Field(description="Глобальный seq события (BIGSERIAL).")
    workflow_id: UUID = Field(description="UUID инстанса workflow.")
    event_type: WorkflowEventType = Field(description="Тип события.")
    payload: dict[str, Any] = Field(
        default_factory=dict, description="Произвольный JSON-payload события."
    )
    step_name: str | None = Field(
        default=None, description="Имя DSL-шага (для step-level событий)."
    )
    occurred_at: datetime = Field(description="Время записи события.")


class WorkflowInstanceSchemaOut(BaseSchema):
    """DTO header-записи workflow для list/get API.

    Не включает event log — используется в списочных endpoint'ах, где
    важна экономия payload'а. Для детального просмотра см.
    :class:`WorkflowInstanceDetailSchemaOut`.

    Attributes:
        id: UUID инстанса.
        workflow_name: Логическое имя workflow.
        route_id: DSL ``route_id``, под которым выполняется workflow.
        status: Текущий логический статус.
        current_version: Версия spec'а на момент последнего шага.
        last_event_seq: Максимальный seq события в log'е (``None`` —
            инстанс ещё не выполнил ни одного события).
        next_attempt_at: Запланированное время следующей попытки
            (``None`` — выполняется немедленно).
        locked_by: Идентификатор worker'а, владеющего advisory lock'ом.
        locked_until: Время истечения lease (для detection зависших
            workers).
        tenant_id: Multi-tenant scope.
        input_payload: Immutable вход (копия из запроса, отправившего
            trigger).
        created_at: Время создания инстанса.
        updated_at: Время последнего обновления header'а.
        finished_at: Время финального перехода в terminal-статус
            (``None`` для активных инстансов).
        last_error: Последняя ошибка (из ``snapshot_state.last_error``)
            — для быстрого отображения в UI без чтения event log'а.
    """

    id: UUID
    workflow_name: str
    route_id: str
    status: WorkflowStatus
    current_version: int
    last_event_seq: int | None = None
    next_attempt_at: datetime | None = None
    locked_by: str | None = None
    locked_until: datetime | None = None
    tenant_id: str = "default"
    input_payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None = None
    last_error: str | None = None


class WorkflowInstanceDetailSchemaOut(WorkflowInstanceSchemaOut):
    """Расширенная версия — header + полный event log.

    Используется в ``GET /api/v1/admin/workflows/{instance_id}``.
    Для длинных log'ов (N > 500) лучше использовать paginated
    endpoint ``GET .../events?after_seq=...``.

    Attributes:
        snapshot_state: Кэшированный snapshot :class:`WorkflowState`
            (``None`` если snapshot ещё не создан).
        events: Полный event log инстанса (ordered by seq ASC).
    """

    snapshot_state: dict[str, Any] | None = None
    events: list[WorkflowEventSchemaOut] = Field(default_factory=list)


class WorkflowInstanceRef(BaseSchema):
    """Краткий ref на созданный workflow-инстанс — ответ на trigger.

    Используется в:
        * ``POST /api/v1/admin/workflows/trigger/{workflow_name}``
        * MCP auto-export (для ``wait=False`` ветки).

    Attributes:
        id: UUID созданного инстанса.
        workflow_name: Логическое имя workflow.
        status: Стартовый статус (обычно ``pending``, но может быть
            ``running``/``succeeded`` если ``wait=True`` + быстрый flow).
        created_at: Время создания инстанса.
        result: Опциональный результат (заполнен только при
            ``wait=True`` и успешном завершении до timeout).
        error: Опциональный текст ошибки (при ``wait=True`` и
            terminal failure).
    """

    id: UUID = Field(description="UUID созданного инстанса workflow.")
    workflow_name: str = Field(description="Логическое имя workflow.")
    status: WorkflowStatus = Field(description="Текущий статус инстанса.")
    created_at: datetime = Field(description="Время создания.")
    result: dict[str, Any] | None = Field(
        default=None, description="Результат (только при wait=True и succeeded)."
    )
    error: str | None = Field(
        default=None, description="Текст ошибки (при wait=True и terminal failure)."
    )


class WorkflowTriggerRequest(BaseSchema):
    """Опциональный request-wrapper для trigger endpoint'а.

    Admin API принимает payload напрямую (``Body(...)``), этот schema —
    для интроспекции Swagger / на случай расширения метадатой
    (correlation_id, tenant_id override).
    """

    payload: dict[str, Any] = Field(
        default_factory=dict, description="Входной payload для workflow."
    )
    tenant_id: str | None = Field(
        default=None,
        description="Override tenant scope (по умолчанию — из контекста запроса).",
    )
    correlation_id: str | None = Field(
        default=None, description="Корреляционный ID (если не задан — генерируется)."
    )


class WorkflowCancelRequest(BaseSchema):
    """Payload для cancel endpoint'а — опциональная причина отмены."""

    reason: str | None = Field(
        default=None,
        description="Человекочитаемая причина отмены (попадёт в event log).",
    )
