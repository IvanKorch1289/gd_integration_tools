"""MCP auto-export для durable workflows (IL-WF1.5).

Каждый workflow, зарегистрированный в :class:`WorkflowRegistry`,
экспортируется как отдельный MCP tool с префиксом ``workflow_`` —
чтобы AI-агенты (CrewAI / LangChain / LangGraph / Claude Desktop)
могли запускать бизнес-процессы через стандартный MCP-протокол.

Механизм:
    * :func:`register_workflow_tools` итерирует
      ``workflow_registry.list_all()``.
    * Для каждого descriptor'а создаётся отдельная tool-функция
      через фабрику :func:`_build_workflow_tool` (замыкание по
      ``workflow_name``, чтобы MCP видел каждый tool отдельно).
    * Name tool'а = ``workflow_{name}`` (точки в имени заменяются на
      подчёркивания — MCP требует valid identifier).

Вспомогательные tools:
    * ``workflow_list`` — список зарегистрированных workflow'ов с
      description / tags / input-schema.
    * ``workflow_status`` — проверить статус ранее запущенного
      инстанса по UUID.

Интеграция: вызывается из ``mcp_server.create_mcp_server()`` после
``register_mcp_tools()``. Регистрация идемпотентна — повторный вызов
безопасен (FastMCP warn'ит на duplicate).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

import orjson

from src.backend.workflows.registry import WorkflowDescriptor, workflow_registry

if TYPE_CHECKING:
    from pydantic import BaseModel

__all__ = ("register_workflow_tools",)

_logger = logging.getLogger("mcp.workflow_tools")


def register_workflow_tools(mcp: Any) -> None:
    """Регистрирует все workflow'ы из :class:`WorkflowRegistry` как MCP tools.

    Args:
        mcp: Экземпляр :class:`fastmcp.FastMCP`.
    """
    descriptors = workflow_registry.list_all()
    for descriptor in descriptors:
        route_id = workflow_registry.get_route_id(descriptor.name)
        if route_id is None:  # defensive
            _logger.warning(
                "skipping workflow %s: no route_id binding", descriptor.name
            )
            continue
        _build_workflow_tool(mcp, descriptor, route_id)

    _register_catalog_tools(mcp)

    _logger.info("Зарегистрировано %d workflow MCP tools", len(descriptors))


def _sanitize_tool_name(name: str) -> str:
    """Конвертирует ``workflow.name`` в валидный MCP tool name.

    MCP требует ``[A-Za-z0-9_-]+``. Точки заменяем на подчёркивания,
    префиксируем ``workflow_`` для namespace-изоляции от action tools.
    """
    safe = name.replace(".", "_").replace("-", "_").replace("/", "_")
    return f"workflow_{safe}"


def _tool_description(descriptor: WorkflowDescriptor) -> str:
    """Формирует человекочитаемое описание для MCP-клиента."""
    parts: list[str] = []
    if descriptor.description:
        parts.append(descriptor.description)
    else:
        parts.append(f"Запускает durable workflow '{descriptor.name}'.")
    if descriptor.tags:
        parts.append(f"Теги: {', '.join(descriptor.tags)}.")
    parts.append(
        "Параметры: payload (dict), wait (bool, default=False), "
        "timeout_s (int, default=300)."
    )
    return " ".join(parts)


def _build_workflow_tool(
    mcp: Any, descriptor: WorkflowDescriptor, route_id: str
) -> None:
    """Регистрирует один workflow как отдельный MCP tool.

    Замыкание по ``descriptor`` / ``route_id`` — каждый tool имеет
    свой независимый handler.

    Если у descriptor'а задана ``input_schema`` (Pydantic-модель) —
    она валидирует payload перед созданием инстанса. JSON-Schema
    для MCP-клиента не выставляется напрямую в FastMCP (sig-based),
    но описание в ``description`` упоминает обязательные поля.
    """
    tool_name = _sanitize_tool_name(descriptor.name)
    description = _tool_description(descriptor)
    input_schema = descriptor.input_schema

    @mcp.tool(name=tool_name, description=description)
    async def tool_handler(
        payload: str = "{}",
        wait: bool = False,
        timeout_s: int = 300,
        _workflow_name: str = descriptor.name,
        _route_id: str = route_id,
        _input_schema: type["BaseModel"] | None = input_schema,
    ) -> str:
        """MCP tool-handler для запуска workflow'а.

        payload передаётся как JSON-строка (MCP-конвенция для сложных
        типов). Парсится → валидируется → создаётся instance.
        Возвращает JSON-строку с полями ``workflow_id``, ``status``,
        опционально ``result``/``error``.
        """
        try:
            parsed_payload = orjson.loads(payload) if payload else {}
        except orjson.JSONDecodeError, TypeError:
            return orjson.dumps(
                {"error": "invalid JSON payload", "raw": payload}
            ).decode()

        if _input_schema is not None:
            try:
                validated = _input_schema.model_validate(parsed_payload)
                parsed_payload = validated.model_dump(mode="json")
            except Exception as exc:  # noqa: BLE001
                return orjson.dumps(
                    {"error": f"payload validation failed: {exc}"}
                ).decode()

        try:
            result = await _trigger_and_maybe_wait(
                workflow_name=_workflow_name,
                route_id=_route_id,
                payload=parsed_payload,
                wait=wait,
                timeout_s=timeout_s,
            )
            return orjson.dumps(result, default=str).decode()
        except Exception as exc:  # noqa: BLE001
            _logger.exception("workflow tool %s failed: %s", tool_name, exc)
            return orjson.dumps({"error": str(exc)}).decode()


async def _trigger_and_maybe_wait(
    *,
    workflow_name: str,
    route_id: str,
    payload: dict[str, Any],
    wait: bool,
    timeout_s: int,
) -> dict[str, Any]:
    """Делегирует создание инстанса через единый dispatch_action и,
    при ``wait=True``, polling'ом ждёт terminal-статуса.

    Делается без зависимости от FastAPI — MCP-сервер живёт
    отдельным процессом (см. `mcp_server.py`), импорты ленивые.
    """
    import asyncio
    from datetime import datetime, timezone

    from src.backend.core.di.providers import (
        get_workflow_state_store_provider,
        get_workflow_status_enum_provider,
    )
    from src.backend.dsl.commands.registry import action_handler_registry
    from src.backend.entrypoints.base import dispatch_action

    WorkflowStatus = get_workflow_status_enum_provider()
    WorkflowInstanceStore = get_workflow_state_store_provider()
    store = WorkflowInstanceStore()

    # Приоритет — через action-registry, иначе fallback на store напрямую.
    if action_handler_registry.is_registered("workflows.trigger"):
        dispatched = await dispatch_action(
            action="workflows.trigger",
            payload={
                "workflow_name": workflow_name,
                "route_id": route_id,
                "payload": payload,
            },
            source="mcp",
        )
        if isinstance(dispatched, dict) and "id" in dispatched:
            instance_id = UUID(str(dispatched["id"]))
        elif isinstance(dispatched, UUID):
            instance_id = dispatched
        else:
            instance_id = UUID(str(dispatched))
    else:
        instance_id = await store.create(
            workflow_name=workflow_name, route_id=route_id, input_payload=payload
        )

    if not wait:
        return {
            "workflow_id": str(instance_id),
            "status": WorkflowStatus.pending.value,
            "message": ("Workflow queued. Use workflow_status tool to check progress."),
        }

    # Polling до terminal или timeout'а.
    terminal = {
        WorkflowStatus.succeeded,
        WorkflowStatus.failed,
        WorkflowStatus.cancelled,
    }
    deadline = datetime.now(timezone.utc).timestamp() + timeout_s
    poll_interval_s = 2.0

    while True:
        row = await store.get(instance_id)
        if row is None:
            return {"workflow_id": str(instance_id), "error": "instance disappeared"}
        if row.status in terminal:
            last_error: str | None = None
            result_payload: Any = None
            if isinstance(row.snapshot_state, dict):
                raw_err = row.snapshot_state.get("last_error")
                if isinstance(raw_err, str):
                    last_error = raw_err
                if row.status == WorkflowStatus.succeeded:
                    result_payload = row.snapshot_state.get("exchange_snapshot")

            return {
                "workflow_id": str(instance_id),
                "status": row.status.value,
                "result": result_payload,
                "error": last_error if row.status == WorkflowStatus.failed else None,
                "finished_at": (
                    row.finished_at.isoformat() if row.finished_at else None
                ),
            }
        if datetime.now(timezone.utc).timestamp() >= deadline:
            return {
                "workflow_id": str(instance_id),
                "status": row.status.value,
                "timeout": True,
                "message": (
                    f"Workflow still running after {timeout_s}s — "
                    "check status via workflow_status tool."
                ),
            }
        await asyncio.sleep(poll_interval_s)


# --- Catalog / introspection tools ------------------------------------


def _register_catalog_tools(mcp: Any) -> None:
    """Регистрирует служебные tools для обнаружения и статуса."""

    @mcp.tool(
        name="workflow_list",
        description=(
            "Список всех зарегистрированных durable workflows с "
            "описаниями, тегами и input-схемами. Используйте для "
            "обнаружения доступных бизнес-процессов."
        ),
    )
    async def workflow_list() -> str:
        from src.backend.entrypoints.api.v1.endpoints.admin_workflows import (
            input_schema_json,
        )

        items: list[dict[str, Any]] = []
        for descriptor in workflow_registry.list_all():
            items.append(
                {
                    "name": descriptor.name,
                    "description": descriptor.description,
                    "tags": list(descriptor.tags),
                    "max_attempts": descriptor.max_attempts,
                    "tool_name": _sanitize_tool_name(descriptor.name),
                    "route_id": workflow_registry.get_route_id(descriptor.name),
                    "input_schema": input_schema_json(descriptor.input_schema),
                    "output_schema": input_schema_json(descriptor.output_schema),
                }
            )
        return orjson.dumps(items, default=str).decode()

    @mcp.tool(
        name="workflow_status",
        description=(
            "Получить текущий статус ранее запущенного workflow-инстанса "
            "по UUID. Возвращает status / last_error / finished_at."
        ),
    )
    async def workflow_status(instance_id: str) -> str:
        from src.backend.core.di.providers import get_workflow_state_store_provider

        try:
            uid = UUID(instance_id)
        except (ValueError, TypeError):
            return orjson.dumps({"error": f"invalid UUID: {instance_id!r}"}).decode()

        WorkflowInstanceStore = get_workflow_state_store_provider()
        store = WorkflowInstanceStore()
        row = await store.get(uid)
        if row is None:
            return orjson.dumps(
                {"error": f"instance '{instance_id}' not found"}
            ).decode()

        last_error: str | None = None
        if isinstance(row.snapshot_state, dict):
            raw_err = row.snapshot_state.get("last_error")
            if isinstance(raw_err, str):
                last_error = raw_err

        return orjson.dumps(
            {
                "workflow_id": str(row.id),
                "workflow_name": row.workflow_name,
                "status": row.status.value,
                "last_event_seq": row.last_event_seq,
                "next_attempt_at": (
                    row.next_attempt_at.isoformat() if row.next_attempt_at else None
                ),
                "created_at": row.created_at.isoformat(),
                "finished_at": (
                    row.finished_at.isoformat() if row.finished_at else None
                ),
                "last_error": last_error,
                "tenant_id": row.tenant_id,
            },
            default=str,
        ).decode()
