"""S60 W3 — lifecycle.py part of setup_infra decomp.

Funcs: _register_default_degradation_features, perform_infrastructure_operation, starting, ending.

lifecycle orchestrators (degradation features + perform + starting/ending).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from inspect import isawaitable
from typing import Any

from src.backend.core.logging import get_logger
from src.backend.plugins.composition.setup_infra.health import _register_health_checks
from src.backend.plugins.composition.setup_infra.pools import (
    _clickhouse_enabled,
    _redis_enabled,
    _register_pools_in_unified_manager,
    _warmup_connection_pools,
)
from src.backend.plugins.composition.setup_infra.scheduler_leader import (
    _start_scheduler_with_leader_election,
    _stop_scheduler_if_leader,
)
from src.backend.plugins.composition.setup_infra.workflow_audit import (
    _close_workflow_audit_sink,
    _init_workflow_audit_sink,
)

app_logger = get_logger("application")

OperationItem = tuple[
    str, Callable[[], Any] | Callable[[], Awaitable[Any]], Callable[[], bool] | None
]


def _register_default_degradation_features() -> None:
    """Backbone-регистрация типовых features в GracefulDegradationRegistry.

    Real-handler'ы — заглушки ``_unsupported_full/_unsupported_degraded``;
    feature-owner подменяет их явным ``registry.register(...)`` при
    инициализации соответствующего модуля. Эта функция гарантирует, что
    admin-снимок ``/tech/degradation/snapshot`` сразу содержит ожидаемые
    feature-имена и operations dashboard не выглядит пустым.
    """
    from src.backend.core.resilience.graceful_degradation import (
        DegradationFeature,
        get_graceful_degradation_registry,
    )

    registry = get_graceful_degradation_registry()
    app_logger = get_logger("application")  # S62 W5: was get_log_manager()

    async def _unsupported_full(*_: Any, **__: Any) -> None:
        # Заглушка — owner feature'а обязан явно зарегистрировать
        # real-handler через registry.register(...).
        raise NotImplementedError("full_handler не зарегистрирован")

    async def _unsupported_degraded(*_: Any, **__: Any) -> None:
        raise NotImplementedError("degraded_handler не зарегистрирован")

    default_features = (
        "ai.llm_call",
        "rag.retrieval",
        "external.api_call",
        "cache.lookup",
    )
    for name in default_features:
        if registry.is_registered(name):
            continue
        registry.register(
            DegradationFeature(
                name=name,
                full_handler=_unsupported_full,
                degraded_handler=_unsupported_degraded,
            )
        )
    app_logger.info(
        "GracefulDegradationRegistry: %d default features зарегистрированы",
        len(default_features),
    )


async def perform_infrastructure_operation(components: list[OperationItem]) -> None:
    """
    Последовательно выполняет startup/shutdown операции инфраструктуры.

    Логика:
    - порядок выполнения фиксирован и управляется списком `components`;
    - каждый элемент содержит опциональный guard ``enabled_check``;
      если он возвращает ``False``, операция пропускается с info-логом
      (используется для dev_light, где Redis/S3 отключены);
    - при первой критической ошибке выполнение прерывается;
    - подробности ошибки логируются в app_logger.
    """
    app_logger = get_logger("application")  # S62 W5: was get_log_manager()
    for name, operation, enabled_check in components:
        if enabled_check is not None and not enabled_check():
            app_logger.info(
                "Операция инфраструктуры пропущена (disabled)",
                extra={"operation": name},
            )
            continue
        try:
            result = operation()

            if isawaitable(result):
                await result

            app_logger.info(
                "Операция инфраструктуры выполнена успешно", extra={"operation": name}
            )
        except Exception as exc:
            app_logger.critical(
                "Ошибка при выполнении операции инфраструктуры",
                extra={"operation": name, "error": str(exc)},
                exc_info=True,
            )
            raise


async def starting() -> None:
    """
    Инициализирует инфраструктурные зависимости приложения.
    """
    await perform_infrastructure_operation(starting_operations)


async def ending() -> None:
    """
    Корректно завершает инфраструктурные зависимости приложения.
    """
    await perform_infrastructure_operation(ending_operations)


starting_operations: list[OperationItem] = [
    (
        "register_default_degradation_features",
        _register_default_degradation_features,
        None,
    ),
    ("register_health_checks", _register_health_checks, None),
    ("register_pools_in_unified_manager", _register_pools_in_unified_manager, None),
    ("warmup_connection_pools", _warmup_connection_pools, None),
    ("init_workflow_audit_sink", _init_workflow_audit_sink, _clickhouse_enabled),
    (
        "start_scheduler_with_leader_election",
        _start_scheduler_with_leader_election,
        _redis_enabled,
    ),
]

ending_operations: list[OperationItem] = [
    ("close_workflow_audit_sink", _close_workflow_audit_sink, None),
    ("stop_scheduler_if_leader", _stop_scheduler_if_leader, None),
]
