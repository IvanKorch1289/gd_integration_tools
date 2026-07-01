"""S111 W2 — startup phase extracted from ``lifespan.py``.

Contains the bulk of the FastAPI app's startup sequence:

1. **Observability baseline**: TaskRegistry, OTel traces, OTel metrics
2. **Config validation**: cross-settings ConfigValidator (fail-fast gate)
3. **Sentry / LogSinks init** (graceful, never blocks)
4. **DI / storage singletons / Redis cluster** setup
5. **Service registration**: ``register_all_services``, AI Safety, DSL
6. **Resilience / snapshot jobs / protocol providers**
7. **PluginLoader** (in-tree + entry_points)
8. **V11 loader + hot reload**
9. **Outbox dispatcher / stuck monitor** (feature-flag-gated)
10. **Workflow runtime + schema registry + feature-flag broadcaster**

Each step is wrapped in ``try/except`` to ensure startup is **best-effort**:
only hard failures (DI registry broken, etc.) propagate. Missing optional
deps (aioboto3, asyncssh, OTel, Sentry) log a warning and continue.

The original ``_register_outbox_dispatcher()`` (S64 W3 cutover) lives here
and is re-exported from ``lifespan.py`` for backward compatibility
(existing test ``test_outbox_dispatcher_cutover.py`` references it).
"""

from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING

from src.backend.core.logging import get_logger

if TYPE_CHECKING:
    from fastapi import FastAPI

_logger = get_logger("application.startup")


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

__all__ = ("_register_outbox_dispatcher", "run_startup")


# ─────────────────────────────────────────────────────────────────────────────
# Outbox dispatcher cutover (S64 W3) — moved from lifespan.py
# ─────────────────────────────────────────────────────────────────────────────


async def _start_event_bus(app: FastAPI) -> None:
    """S133 W4 — стартует EventBus при включённом флаге.

    ponytail: minimal wiring. Если Redis недоступен — log+continue,
    DSL-процессор fallback'ит на ``exchange.properties``.
    S46 fix: bus.start() обёрнут в asyncio.timeout(5) — FastStream Redis
    broker падает с TimeoutError (BaseException) при недоступном Redis,
    штатный except Exception не ловит. Ловим BaseException.
    """
    try:
        from src.backend.core.config.features import feature_flags
        from src.backend.core.config.settings import settings
        from src.backend.core.messaging.event_bus import get_event_bus

        if not feature_flags.eventbus_facade and not feature_flags.eventbus_dsl_enabled:
            return

        bus = get_event_bus()
        try:
            async with asyncio.timeout(5.0):
                await bus.start(settings.redis.redis_url)
        except TimeoutError:
            _logger.warning(
                "EventBus start timed out (Redis %s unavailable) — skipping",
                settings.redis.redis_url,
            )
            return
        app.state.event_bus = bus
        _logger.info("EventBus started on %s", settings.redis.redis_url)
    except BaseException as exc:  # noqa: BLE001 — ловим TimeoutError, CancelledError и др.
        _logger.warning("EventBus startup skipped: %s", exc)


async def _register_outbox_dispatcher(app: FastAPI) -> None:
    """S64 W3 — outbox dispatcher cutover: legacy worker ↔ new dispatcher.

    Под feature flag-ом ``outbox_settings.enabled`` (default OFF):

    * **False** (default) → ``start_outbox_worker()`` (legacy APScheduler,
      не multi-instance safe, см. ``outbox_worker.py``).
    * **True** → ``start_outbox_dispatcher()`` (S64 W1+W3: multi-instance
      safe через ``claim_pending`` с advisory lock + FOR UPDATE SKIP LOCKED).

    Adapter-ы (claim_pending → OutboxEvent, OutboxEvent → mark_sent)
    инкапсулированы внутри этой функции. ``_outbox_msg_id`` кодируется
    в ``correlation_id`` (формат ``outbox_msg_id:<N>``) для ack-mapping.

    **NB**: исключения НЕ raise'ятся наружу — outbox не блокирует
    startup (best-effort), аналогично legacy поведению.
    """
    try:
        from src.backend.core.config.services.outbox import outbox_settings

        if outbox_settings.enabled:
            # S64 W3: новый OutboxDispatcher path (multi-instance safe).
            # Worker ID: HOSTNAME env (K8s pod name) → socket.gethostname()
            import os as _os
            import socket as _socket
            from collections.abc import Sequence as _Sequence
            from uuid import uuid4

            from src.backend.core.messaging.outbox import FakeOutbox, OutboxEvent
            from src.backend.infrastructure.messaging.outbox.lifecycle import (
                start_outbox_dispatcher,
            )
            from src.backend.infrastructure.repositories import outbox as outbox_repo
            from src.backend.infrastructure.workflow.outbox_worker import _publish

            _worker_id = _os.environ.get("HOSTNAME") or _socket.gethostname()

            def _topic_to_transport(topic: str) -> str:
                """``kafka:orders.created`` → ``kafka`` для OutboxEvent.transport."""
                if ":" in topic:
                    proto = topic.split(":", 1)[0].lower()
                    if proto in ("kafka", "rabbit", "redis", "nats", "http"):
                        return proto
                return "kafka"  # default (legacy worker)

            async def _pending_source(limit: int) -> _Sequence[OutboxEvent]:
                """Adapter: claim_pending (W1) → OutboxEvent list.

                Использует S64 W1 claim_pending (advisory lock +
                FOR UPDATE SKIP LOCKED) → multi-instance safe.
                Кодирует ``outbox_msg_id:<N>`` в ``correlation_id``
                для последующего ack (OutboxEvent не имеет ``id``/``headers``).
                """
                msgs = await outbox_repo.claim_pending(
                    limit=limit, worker_id=_worker_id
                )
                result: list[OutboxEvent] = []
                for m in msgs:
                    # Prefer original correlation_id from headers;
                    # else use the outbox_msg_id marker (для ack).
                    original_cid = (m.headers or {}).get("correlation_id")
                    cid = original_cid or f"outbox_msg_id:{m.id}"
                    result.append(
                        OutboxEvent(
                            event_id=uuid4().hex,
                            transport=_topic_to_transport(m.topic),
                            action=m.topic,
                            payload=m.payload,
                            correlation_id=cid,
                        )
                    )
                return result

            async def _ack(event: OutboxEvent) -> None:
                """Adapter: OutboxEvent → mark_sent (по ``correlation_id``).

                Приоритет: если ``correlation_id`` начинается с
                ``outbox_msg_id:`` — это marker, ack по msg.id.
                Иначе (original CID) — нет msg.id, skip ack (safety).
                """
                cid = event.correlation_id or ""
                if cid.startswith("outbox_msg_id:"):
                    raw_id = cid.removeprefix("outbox_msg_id:")
                    try:
                        await outbox_repo.mark_sent(int(raw_id))
                    except (ValueError, TypeError):
                        return

            async def _deliverer(event: OutboxEvent) -> None:
                """Adapter: reuse legacy ``_publish`` (K8/F2 Wave 2)."""
                await _publish(
                    event.action,
                    event.payload,
                    {"correlation_id": event.correlation_id or ""},
                )

            await start_outbox_dispatcher(
                app=app,
                backend=FakeOutbox(),
                pending_source=_pending_source,
                ack=_ack,
                deliverer=_deliverer,
            )
            _logger.info(
                "S64 W3: OutboxDispatcher started (worker_id=%s, "
                "outbox_settings.enabled=True)",
                _worker_id,
            )
        else:
            # Legacy APScheduler worker (default, backwards-compat).
            from src.backend.infrastructure.workflow.outbox_worker import (
                start_outbox_worker,
            )

            start_outbox_worker(interval_seconds=5, batch_size=100)
            _logger.info(
                "Legacy outbox worker registered "
                "(outbox_settings.enabled=False, S64 W3 cutover not active)."
            )
    except Exception as exc:
        # Outbox-worker не критичен для базовой работоспособности
        # (например, dev_light без RabbitMQ) — startup продолжается.
        _logger.warning("Outbox worker registration skipped: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# Startup phase orchestrator
# ─────────────────────────────────────────────────────────────────────────────


async def run_startup(app: FastAPI, task_registry: object) -> None:
    """Run the full startup phase (moved from lifespan() context manager body).

    Same ordering, same error semantics as the original lifespan() try-block:
    hard errors propagate, optional subsystems log+continue.
    """
    # Lazy imports (avoid pre-existing import-bugs in composition package —
    # mirrors the strategy used in test_outbox_dispatcher_cutover.py).
    from src.backend.plugins.composition.lifecycle.bootstrap import (
        bootstrap_resilience_coordinator,
        bootstrap_snapshot_job,
        register_storage_singletons,
        validate_cache_layers,
    )
    from src.backend.plugins.composition.lifecycle.plugin_loader import (
        bootstrap_v11_plugin_loader,
        bootstrap_v11_route_loader,
        start_v11_hot_reload,
    )
    from src.backend.plugins.composition.lifecycle.protocols import (
        register_protocol_providers,
    )
    from src.backend.plugins.composition.lifecycle.watchers import (
        start_dsl_yaml_watcher,
    )

    # ── Observability baseline ──
    if os.environ.get("OTEL_ENABLED", "false").lower() == "true":
        try:
            from src.backend.infrastructure.observability.otel import configure_otel

            configure_otel(
                service_name=os.environ.get("OTEL_SERVICE_NAME", "gd_integration"),
                exporter=os.environ.get("OTEL_EXPORTER", "console"),
                endpoint=os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or None,
                environment=os.environ.get("APP_ENVIRONMENT", "development"),
            )
        except Exception as otel_exc:
            _logger.warning(
                "OTel baseline configure skipped: %s "
                "(приложение продолжит без базового TracerProvider)",
                otel_exc,
            )

    if os.environ.get("OTLP_METRICS_ENABLED", "false").lower() == "true":
        try:
            from src.backend.infrastructure.observability.otel import setup_otel_metrics

            setup_otel_metrics(
                service_name=os.environ.get("OTEL_SERVICE_NAME", "gd_integration"),
                endpoint=(
                    os.environ.get("OTLP_METRICS_ENDPOINT")
                    or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
                    or None
                ),
                export_interval_seconds=int(
                    os.environ.get("OTLP_METRICS_EXPORT_INTERVAL_SECONDS", "60")
                ),
                environment=os.environ.get("APP_ENVIRONMENT", "development"),
                insecure=(
                    os.environ.get("OTLP_METRICS_INSECURE", "true").lower() == "true"
                ),
            )
        except Exception as metrics_exc:
            _logger.warning(
                "OTel metrics configure skipped: %s "
                "(приложение продолжит без OTLP metrics-канала)",
                metrics_exc,
            )

    # ── DI / config ──
    from src.backend.plugins.composition.di import register_app_state

    # Cross-settings ConfigValidator (Sprint 16 Wave 3, CP-24, B-2, B-9).
    try:
        from src.backend.core.config.settings import settings as _cv_settings
        from src.backend.core.config.validator import (
            ConfigSeverity,
            ProductionConfigError,
            validate_startup_config,
        )
        from src.backend.core.config.waf import waf_settings as _cv_waf_settings

        _cv_violations = validate_startup_config(_cv_settings, _cv_waf_settings)
        for _cv_v in _cv_violations:
            _payload = (
                "[%s] %s field=%s recommendation=%s context=%s",
                _cv_v.code,
                _cv_v.message,
                _cv_v.field,
                _cv_v.recommendation,
                _cv_v.context,
            )
            if _cv_v.severity == ConfigSeverity.CRITICAL:
                _logger.critical(*_payload)
            elif _cv_v.severity == ConfigSeverity.WARNING:
                _logger.warning(*_payload)
            else:
                _logger.info(*_payload)
    except ProductionConfigError as cfg_exc:
        _logger.critical("Конфигурация production не прошла валидацию: %s", cfg_exc)
        raise
    except Exception as cfg_exc:
        _logger.warning(
            "ConfigValidator skipped: %s "
            "(приложение продолжит без cross-settings проверки)",
            cfg_exc,
        )

    # ── Sentry init ──
    try:
        from src.backend.infrastructure.observability.sentry_init import init_sentry

        init_sentry()
    except Exception as sentry_exc:
        _logger.warning(
            "Sentry init skipped: %s (приложение продолжит без error tracking)",
            sentry_exc,
        )

    # ── LogSink router (Wave 2.5) ──
    try:
        from src.backend.infrastructure.logging import init_log_sinks

        init_log_sinks()
    except Exception as log_exc:
        _logger.warning(
            "LogSink router init skipped: %s (приложение продолжит на stdlib-логах)",
            log_exc,
        )

    register_app_state(app)
    register_storage_singletons(app)

    # ── Redis cluster adapter (Sprint 3 К2 W1) ──
    if os.environ.get("REDIS_CLUSTER_ENABLED", "false").lower() == "true":
        try:
            nodes_env = os.environ.get("REDIS_CLUSTER_NODES", "").strip()
            if not nodes_env:
                _logger.warning(
                    "REDIS_CLUSTER_ENABLED=true, но REDIS_CLUSTER_NODES пуст — пропуск"
                )
            else:
                from redis.asyncio.cluster import ClusterNode

                from src.backend.infrastructure.cache.redis_cluster import (
                    RedisClusterAdapter,
                )

                parsed_nodes: list[ClusterNode] = []
                for node_entry in nodes_env.split(","):
                    host, _, port = node_entry.strip().partition(":")
                    if not host:
                        continue
                    parsed_nodes.append(ClusterNode(host=host, port=int(port or 6379)))

                cluster_password = os.environ.get("REDIS_CLUSTER_PASSWORD") or None
                adapter = RedisClusterAdapter(
                    startup_nodes=parsed_nodes,
                    max_connections=int(
                        os.environ.get("REDIS_CLUSTER_MAX_CONNECTIONS", "50")
                    ),
                    socket_keepalive=True,
                    health_check_interval=int(
                        os.environ.get("REDIS_CLUSTER_HEALTH_CHECK_INTERVAL", "30")
                    ),
                    password=cluster_password,
                )
                app.state.redis_cluster_adapter = adapter
                _logger.info(
                    "RedisClusterAdapter зарегистрирован: nodes=%d", len(parsed_nodes)
                )
        except Exception as rc_exc:
            _logger.warning(
                "RedisClusterAdapter bootstrap skipped: %s "
                "(приложение продолжит без cluster-режима)",
                rc_exc,
            )

    # ── Service registration ──
    from src.backend.plugins.composition.service_setup import register_all_services

    register_all_services()

    # AI Safety cleanup-loop (Wave 1.6, S1).
    try:
        from src.backend.plugins.composition.ai_safety_setup import start_ai_safety

        await start_ai_safety(app)
    except Exception as ai_safety_exc:
        _logger.warning(
            "AI safety bootstrap skipped: %s "
            "(приложение продолжит без AI workspace cleanup-loop)",
            ai_safety_exc,
        )

    # ── DSL commands / routes ──
    from src.backend.dsl.commands.setup import register_action_handlers
    from src.backend.dsl.routes import register_dsl_routes

    register_action_handlers()
    register_dsl_routes()

    bootstrap_resilience_coordinator(app)
    bootstrap_snapshot_job(app)
    await start_dsl_yaml_watcher(app)

    # ── Starting infrastructure (setup_infra) ──
    from src.backend.plugins.composition.setup_infra import starting

    await starting()
    await register_protocol_providers()
    validate_cache_layers()

    # ── EventBus startup (S133 W4) ──
    await _start_event_bus(app)

    # ── PluginLoader (in-tree + entry_points) ──
    try:
        from pathlib import Path

        from src.backend.services.plugins import get_plugin_loader

        loader = get_plugin_loader()
        plugins_dir = Path("plugins")
        if plugins_dir.is_dir():
            for entry_raw in plugins_dir.iterdir():
                if not entry_raw.is_dir():
                    continue
                entry = entry_raw  # Path.iterdir() returns Path objects in Python 3.14
                if (entry / "plugin.yaml").is_file():
                    try:
                        await loader.load_from_path(entry)
                    except Exception as plugin_exc:
                        _logger.warning(
                            "In-tree plugin %s skipped: %s", entry.name, plugin_exc
                        )
        try:
            await loader.discover_and_load()
        except Exception as ep_exc:
            _logger.warning("entry_points plugin discovery skipped: %s", ep_exc)
        app.state.plugin_loader = loader
    except Exception as exc:
        _logger.warning("Plugin loader bootstrap skipped: %s", exc)

    # ── V11 loaders + hot reload ──
    await bootstrap_v11_plugin_loader(app)
    await bootstrap_v11_route_loader(app)
    await start_v11_hot_reload(app)

    # ── Outbox dispatcher / stuck monitor ──
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

    # ── Workflow runtime ──
    try:
        from src.backend.plugins.composition.workflow_setup import (
            start_workflow_runtime,
        )

        await start_workflow_runtime(app)
    except Exception as wf_exc:
        _logger.warning("Workflow runtime startup skipped: %s", wf_exc)

    # ── SchemaRegistry (Wave S1/DSL Foundation, Step 6) ──
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

    # ── FeatureFlag broadcaster (Sprint 17 K5 W1, D9) ──
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

    # ── Final: log app ready ──
    from src.backend.dsl.commands.registry import action_handler_registry
    from src.backend.dsl.registry import route_registry

    _logger.info(
        "Приложение успешно запущено: %d actions, %d DSL-маршрутов",
        len(action_handler_registry.list_actions()),
        len(route_registry.list_routes()),
    )
    # ``task_registry`` parameter reserved for future use (e.g., correlating
    # startup tasks to the registry for graceful shutdown). Currently unused.
    _ = task_registry
