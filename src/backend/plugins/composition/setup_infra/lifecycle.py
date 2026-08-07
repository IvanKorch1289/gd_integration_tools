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


async def _register_agent_security_workflow_hooks() -> None:
    """S189: register AgentSecurityFramework workflow hooks.

    До этого hooks были определены, но никогда не регистрировались в
    production startup — только в тестах. Это значит banking/RPA/code/data_export
    workflow-specific проверки НЕ выполнялись в production.
    """
    try:
        from src.backend.core.ai.security import get_agent_security_framework
        from src.backend.core.ai.security.workflow_hooks import (
            register_all_workflow_hooks,
        )

        register_all_workflow_hooks(get_agent_security_framework())
        app_logger.info("AgentSecurityFramework workflow hooks registered")
    except Exception as exc:
        # Non-fatal: framework optional в некоторых профилях
        app_logger.debug(
            "AgentSecurityFramework hooks registration skipped: %s", exc
        )


async def _start_pool_monitors() -> None:
    """Запустить фоновые мониторы пулов (S173 P0 fix).

    Без этого вызова :class:`PoolHealthMonitor` не активен — health-check
    пулов работает только при первом get_metrics() вызове. После добавления
    мониторы стартуют при старте приложения и дают early-warning об исчерпании
    пулов / idle timeouts.

    S173: добавлено как critical fix после Infrastructure audit (start_monitors
    не вызывался → health monitors оставались незапущенными).
    """
    from src.backend.infrastructure.clients.unified_pool_manager import (
        get_unified_pool_manager,
    )

    manager = get_unified_pool_manager()
    if not manager.is_started:  # type: ignore[attr-defined]
        await manager.start_monitors()


async def _start_config_hot_reload() -> None:
    """D-AUDIT-A12-06 fix (cycle 1): wire ConfigHotReloader в production lifespan.

    Без этого вызова hot-reload оставался dead code — ConfigHotReloader
    никогда не вызывал watch()/start() в production. Операторы не могли
    перезагружать config_profiles/*.yml без рестарта приложения.

    Hot-reload активен по умолчанию для всех профилей кроме prod
    (с feature-flag prod_hot_reload_disable).
    """
    from pathlib import Path

    from src.backend.core.config.hot_reload import get_hot_reloader

    reloader = get_hot_reloader()

    # Watch .env (если существует)
    env_path = Path(".env")
    if env_path.exists():
        reloader.watch(env_path)

    # Watch config_profiles/*.yml (canonical paths для hot-reload)
    profiles_dir = Path("config_profiles")
    if profiles_dir.exists() and profiles_dir.is_dir():
        # Watch директорию целиком — watchfiles подхватывает все *.yml файлы
        reloader.watch(profiles_dir)
    else:
        # Fallback: watch отдельные canonical files
        for profile_file in ("base.yml", "dev.yml", "dev_light.yml", "staging.yml", "prod.yml"):
            p = profiles_dir / profile_file
            if p.exists():
                reloader.watch(p)

    # Register reload callback: settings.reload() если доступен
    try:
        from src.backend.core.config.settings import settings

        async def _reload_settings() -> None:
            """Reload settings через hot-reload callback."""
            reload_fn = getattr(settings, "reload", None)
            if callable(reload_fn):
                result = reload_fn()
                if isawaitable(result):
                    await result

        reloader.on_reload(_reload_settings)
    except ImportError:
        app_logger.debug("settings reload callback not registered")

    await reloader.start()
    app_logger.info(
        "Config hot-reload wired: watching %d paths",
        len(reloader._paths),  # type: ignore[attr-defined]
    )


async def _stop_config_hot_reload() -> None:
    """D-AUDIT-A12-06 fix (cycle 1): stop ConfigHotReloader в lifespan shutdown."""
    from src.backend.core.config.hot_reload import get_hot_reloader

    reloader = get_hot_reloader()
    await reloader.stop()
    app_logger.info("Config hot-reload stopped")


starting_operations: list[OperationItem] = [
    (
        "register_default_degradation_features",
        _register_default_degradation_features,
        None,
    ),
    ("register_health_checks", _register_health_checks, None),
    ("register_pools_in_unified_manager", _register_pools_in_unified_manager, None),
    ("warmup_connection_pools", _warmup_connection_pools, None),
    ("start_pool_monitors", _start_pool_monitors, None),  # S173: critical fix
    # S189: register AgentSecurityFramework workflow hooks (banking/rpa/code/data)
    (
        "register_agent_security_workflow_hooks",
        _register_agent_security_workflow_hooks,
        None,
    ),
    # D-AUDIT-A12-06 fix (cycle 1): wire ConfigHotReloader в production lifespan
    (
        "start_config_hot_reload",
        _start_config_hot_reload,
        None,
    ),
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
    # D-AUDIT-A12-06 fix (cycle 1): stop ConfigHotReloader в shutdown
    ("stop_config_hot_reload", _stop_config_hot_reload, None),
]
