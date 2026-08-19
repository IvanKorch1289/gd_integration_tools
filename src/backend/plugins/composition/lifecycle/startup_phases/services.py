"""Sprint 15 P1-12: services startup phases.

Phases:
- :func:`phase_service_registration` — register_all_services
- :func:`phase_ai_gateway_singleton` — AIGateway composition (Sprint 1.5 L5)
- :func:`phase_dsl_commands` — DSL commands/routes
- :func:`phase_watchers` — DSL YAML watcher
- :func:`phase_plugin_loader` — PluginLoader (in-tree + entry_points)
- :func:`phase_v11_loaders` — V11 plugin/route loaders + hot reload
- :func:`phase_outbox_dispatcher` — Outbox dispatcher + stuck monitor
- :func:`phase_workflow_runtime` — Workflow runtime startup
- :func:`phase_schema_registry` — ServiceSchemaRegistry populate
- :func:`phase_feature_flag_broadcaster` — Multi-replica feature flag broadcast
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.backend.core.logging import get_logger

if TYPE_CHECKING:
    from fastapi import FastAPI

_logger = get_logger("application.startup.services")


async def phase_service_registration(app: FastAPI) -> None:  # noqa: ARG001
    """register_all_services — registers all composition-root services."""
    from src.backend.plugins.composition.service_setup import register_all_services

    register_all_services()


async def phase_ai_gateway_singleton(app: FastAPI) -> None:
    """AIGateway composition singleton (Sprint 1.5 L5 Security Chain).

    Регистрирует canonical AIGateway (app.state.ai_gateway + svcs_registry).
    """
    try:
        from src.backend.plugins.composition.workflow_setup import (
            register_ai_gateway_singleton,
        )

        await register_ai_gateway_singleton(app)
    except Exception as aigw_exc:
        _logger.warning(
            "AIGateway composition singleton skipped: %s "
            "(production-wiring guard в AIGateway ловит bare instantiation)",
            aigw_exc,
        )


async def phase_dsl_commands(app: FastAPI) -> None:  # noqa: ARG001
    """DSL commands/routes — registers action handlers + routes."""
    try:
        from src.backend.plugins.composition.bootstrap import register_dsl_commands

        register_dsl_commands()
    except Exception as dsl_exc:
        _logger.warning(
            "DSL commands bootstrap skipped: %s "
            "(routes будут зарегистрированы позже через PluginLoader)",
            dsl_exc,
        )


async def phase_watchers(app: FastAPI) -> None:
    """DSL YAML watcher — hot-reload route definitions."""
    from src.backend.plugins.composition.lifecycle.watchers import (
        start_dsl_yaml_watcher,
    )

    await start_dsl_yaml_watcher(app)


async def phase_plugin_loader(app: FastAPI) -> None:
    """PluginLoader (configured extensions + entry_points)."""
    try:
        from src.backend.services.plugins import get_plugin_loader

        loader = get_plugin_loader()
        await loader.discover_and_load()
        app.state.plugin_loader = loader
    except Exception as exc:
        _logger.warning("Plugin loader bootstrap skipped: %s", exc)


async def phase_v11_loaders(app: FastAPI) -> None:
    """V11 loaders + hot reload."""
    from src.backend.plugins.composition.lifecycle.plugin_loader import (
        bootstrap_v11_plugin_loader,
        bootstrap_v11_route_loader,
        start_v11_hot_reload,
    )

    await bootstrap_v11_plugin_loader(app)
    await bootstrap_v11_route_loader(app)
    await start_v11_hot_reload(app)


async def phase_outbox_dispatcher(app: FastAPI) -> None:
    """Outbox dispatcher + stuck monitor (feature-flag-gated)."""
    from src.backend.plugins.composition.lifecycle.startup import (
        _register_outbox_dispatcher,
    )

    await _register_outbox_dispatcher(app)

    try:
        from src.backend.core.config.features import feature_flags
        from src.backend.infrastructure.messaging.outbox.stuck_monitor import (
            start_outbox_stuck_monitor,
        )

        if getattr(feature_flags, "stuck_monitor_enabled", False):
            threshold = int(
                getattr(feature_flags, "stuck_monitor_threshold_seconds", 300)
            )
            sample_interval = int(
                getattr(feature_flags, "stuck_monitor_sample_interval_seconds", 60)
            )
            await start_outbox_stuck_monitor(
                threshold_seconds=threshold, sample_interval_seconds=sample_interval
            )
            _logger.info(
                "OutboxStuckMonitor started (threshold=%ds, sample=%ds)",
                threshold,
                sample_interval,
            )
    except Exception as exc:
        _logger.warning("OutboxStuckMonitor registration skipped: %s", exc)


async def phase_workflow_runtime(app: FastAPI) -> None:  # noqa: ARG001
    """Workflow runtime startup."""
    try:
        from src.backend.plugins.composition.workflow_setup import (
            start_workflow_runtime,
        )

        await start_workflow_runtime()
    except Exception as wf_exc:
        _logger.warning("Workflow runtime startup skipped: %s", wf_exc)


async def phase_schema_registry(app: FastAPI) -> None:  # noqa: ARG001
    """ServiceSchemaRegistry populate (Wave S1/DSL Foundation, Step 6)."""
    try:
        from src.backend.services.schema_registry import (
            get_schema_registry,
            populate_from_actions,
            populate_from_manifests,
            populate_from_processor_registry,
            populate_from_routes,
        )

        schema_registry = get_schema_registry()
        populate_from_processor_registry(schema_registry)
        populate_from_routes(registry=schema_registry)
        populate_from_actions(schema_registry)
        populate_from_manifests(schema_registry)
        app.state.schema_registry = schema_registry
        _logger.info("ServiceSchemaRegistry заполнен: %s", schema_registry.summary())
    except Exception as sr_exc:
        _logger.warning("ServiceSchemaRegistry bootstrap skipped: %s", sr_exc)


async def phase_feature_flag_broadcaster(app: FastAPI) -> None:  # noqa: ARG001
    """FeatureFlag broadcaster (Sprint 17 K5 W1, D9) — multi-replica."""
    try:
        from src.backend.core.feature_flags.redis_broadcaster import (
            maybe_start_broadcaster,
        )
        from src.backend.core.feature_flags.runtime_overrides import (
            get_runtime_overrides,
        )
        from src.backend.infrastructure.clients.storage.redis import get_redis_client

        redis_kv = getattr(get_redis_client(), "client", None)
        broadcaster = await maybe_start_broadcaster(
            redis_client=redis_kv, overrides=get_runtime_overrides()
        )
        if broadcaster is not None:
            app.state.feature_flag_broadcaster = broadcaster
            _logger.info(
                "FeatureFlagBroadcaster registered: replica_id=%s",
                broadcaster.replica_id,
            )
    except Exception as bcast_exc:
        _logger.warning(
            "FeatureFlagBroadcaster bootstrap skipped: %s "
            "(приложение продолжит без multi-replica propagation)",
            bcast_exc,
        )


__all__ = (
    "phase_service_registration",
    "phase_ai_gateway_singleton",
    "phase_dsl_commands",
    "phase_watchers",
    "phase_plugin_loader",
    "phase_v11_loaders",
    "phase_outbox_dispatcher",
    "phase_workflow_runtime",
    "phase_schema_registry",
    "phase_feature_flag_broadcaster",
)
