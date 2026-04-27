"""Фабрика Prefect-тасков из зарегистрированных actions.

Позволяет автоматически генерировать Prefect-таски для любого
action из ActionHandlerRegistry без ручного написания обёрток.

IL-WF3: модуль помечен DEPRECATED. DSL аналог — workflows напрямую
вызывают ``dispatch_action()`` через processors в WorkflowBuilder;
auto-factory не требуется. MCP auto-export (IL-WF1.5) обеспечивает
доступность workflows как AI-агент tools. Cooldown — H3_PLUS.
"""

import warnings
from typing import Any, Callable

from prefect import task

from src.dsl.commands.registry import action_handler_registry
from src.schemas.invocation import ActionCommandSchema

__all__ = ("create_service_task", "generate_all_tasks")

warnings.warn(
    "`app.workflows.task_factory` (Prefect auto-factory) deprecated "
    "in IL-WF3. DSL workflows использует dispatch_action() напрямую + "
    "MCP auto-export (app.entrypoints.mcp.workflow_tools). "
    "Removal: H3_PLUS cooldown (2026-07-01+).",
    DeprecationWarning,
    stacklevel=2,
)


def create_service_task(
    action: str,
    *,
    name: str | None = None,
    retries: int = 3,
    retry_delay_seconds: int = 10,
    timeout_seconds: int = 300,
) -> Callable:
    """Генерирует Prefect-таск из зарегистрированного action.

    Args:
        action: Имя action из ActionHandlerRegistry.
        name: Человекочитаемое имя таска.
        retries: Количество повторных попыток.
        retry_delay_seconds: Задержка между попытками.
        timeout_seconds: Таймаут выполнения.

    Returns:
        Prefect-таск, который при вызове диспетчеризует action.
    """

    @task(
        name=name or action,
        description=f"Автогенерированный таск для action '{action}'",
        retries=retries,
        retry_delay_seconds=retry_delay_seconds,
        retry_jitter_factor=1,
        timeout_seconds=timeout_seconds,
        log_prints=True,
    )
    async def service_task(**kwargs: Any) -> Any:
        command = ActionCommandSchema(
            action=action, payload=kwargs, meta={"source": "prefect"}
        )
        return await action_handler_registry.dispatch(command)

    return service_task


def generate_all_tasks() -> dict[str, Callable]:
    """Генерирует Prefect-таски для всех зарегистрированных actions.

    Returns:
        Словарь ``{action_name: prefect_task}``.
    """
    return {
        action: create_service_task(action)
        for action in action_handler_registry.list_actions()
    }
