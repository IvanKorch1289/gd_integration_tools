"""S111 W2 — shutdown phase extracted from ``lifespan.py``.

Contains the bulk of the FastAPI app's shutdown sequence (the
``finally`` block in the original lifespan context manager):

1. **Workflow runtime / outbox worker** stop (must happen before
   DSL watcher to let workers complete in-flight workflows).
2. **OutboxStuckMonitor** stop (graceful drain).
3. **DSL YAML watcher** stop.
4. **AI Safety cleanup-loop** stop (must happen before V11 loaders
   to avoid plugin writes during shutdown).
5. **V11 loaders** shutdown (route → plugin order, reversed from
   bootstrap to give ``on_shutdown`` hooks time to run).
6. **PluginLoader** graceful shutdown.
7. **Infrastructure ending()** call.
8. **LogSink** final flush + close.
9. **pyrate_limiter Leaker** shutdown-hook.
10. **OTel metrics** shutdown.
11. **RedisClusterAdapter** close (if registered).
12. **FeatureFlagBroadcaster** stop.
13. **TaskRegistry** graceful cancel of all background tasks
    (LAST so other subsystems can still log during their shutdown).

Each step is wrapped in ``try/except`` to ensure shutdown is
**best-effort**: one subsystem's failure does not block others
from cleaning up. This matches the original lifespan.py finally-block
semantics exactly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.backend.core.logging import get_logger

if TYPE_CHECKING:
    from fastapi import FastAPI

_logger = get_logger("application.shutdown")


__all__ = ("run_shutdown",)


async def run_shutdown(app: FastAPI, task_registry: Any) -> None:
    """Run the full shutdown phase (moved from lifespan() finally block).

    Same ordering, same error semantics as the original lifespan() finally-block.
    Each subsystem is best-effort: log+continue on failure.
    """
    # Lazy imports (avoid pre-existing import-bugs in composition package).
    from src.backend.plugins.composition.lifecycle.v11 import shutdown_v11_loaders
    from src.backend.plugins.composition.lifecycle.watchers import stop_dsl_yaml_watcher

    app = app  # type: ignore[assignment]
    app.state.infrastructure_ready = False

    # ── 1. Workflow runtime / outbox worker ──
    # К3: shutdown workflow runtime до stop_dsl_yaml_watcher, чтобы worker'ы
    # успели завершить свои workflow до закрытия DSL.
    try:
        from src.backend.workflows.outbox_worker import stop_outbox_worker

        await stop_outbox_worker()
    except Exception as wf_stop_exc:
        _logger.warning("Workflow runtime shutdown error: %s", wf_stop_exc)

    # ── 2. OutboxStuckMonitor (S74 W1) ──
    try:
        from src.backend.infrastructure.messaging.outbox.stuck_monitor import (
            stop_outbox_stuck_monitor,
        )

        await stop_outbox_stuck_monitor()
    except Exception as exc:
        _logger.debug("OutboxStuckMonitor stop skipped: %s", exc)

    # ── 3. DSL YAML watcher ──
    try:
        await stop_dsl_yaml_watcher(app)
    except Exception as watcher_exc:
        _logger.warning("DSL YAML watcher shutdown error: %s", watcher_exc)

    # ── 4. AI Safety cleanup-loop ──
    # Wave 1.6 (S1): остановка ДО V11-loaders, плагины могут писать в
    # workspace через AIFsFacade на shutdown.
    try:
        from src.backend.plugins.composition.ai_safety_setup import stop_ai_safety

        await stop_ai_safety(app)
    except Exception as ai_safety_stop_exc:
        _logger.warning("AI safety shutdown error: %s", ai_safety_stop_exc)

    # ── 5. V11 loaders (route → plugin order) ──
    # R1.fin (V11): shutdown в обратном порядке (route → plugin) ДО Wave 4
    # PluginLoader, чтобы их on_shutdown успел отработать до закрытия общих
    # ресурсов.
    try:
        await shutdown_v11_loaders(app)
    except Exception as v11_exc:
        _logger.warning("V11 loaders shutdown error: %s", v11_exc)

    # ── 6. PluginLoader graceful shutdown ──
    plugin_loader = getattr(app.state, "plugin_loader", None)
    if plugin_loader is not None:
        try:
            await plugin_loader.shutdown_all()
        except Exception as plugin_exc:
            _logger.warning("Plugin shutdown error: %s", plugin_exc)

    # ── 7. EventBus lifecycle subscriptions cleanup ──
    # S141: unsubscribe all lifecycle-tracked subscriptions before
    # infrastructure ending.
    try:
        event_bus_facade = getattr(app.state, "eventbus_facade", None)
        if event_bus_facade is not None:
            await event_bus_facade.unsubscribe_all()
    except Exception as eb_exc:
        _logger.debug("EventBusFacade unsubscribe_all skipped: %s", eb_exc)

    # ── 8. Infrastructure ending() ──
    try:
        from src.backend.plugins.composition.setup_infra import ending

        await ending()
    except Exception as shutdown_exc:
        _logger.error(
            "Ошибка при завершении работы приложения: %s",
            str(shutdown_exc),
            exc_info=True,
        )

    _logger.info("Приложение остановлено")

    # ── 9. LogSink final flush + close ──
    # Wave 2.5: делается после ``ending()`` и финального лога, чтобы
    # зафиксировать в sink-ах все события штатной остановки.
    try:
        from src.backend.infrastructure.logging import shutdown_log_sinks

        await shutdown_log_sinks()
    except Exception as sink_exc:
        _logger.warning("LogSink shutdown error: %s", sink_exc)

    # ── 10. pyrate_limiter Leaker shutdown-hook ──
    # Sprint 1 V16 Step 3.4: pyrate_limiter Leaker shutdown-hook.
    # Singleton Limiter из get_default_limiter() запускает фоновую
    # `_leaker.aio_leak_task`, которая течёт без явной остановки.
    try:
        from src.backend.core.resilience._pyrate_compat import shutdown_pyrate_leaker
        from src.backend.entrypoints.dependencies.rate_limit import get_default_limiter

        await shutdown_pyrate_leaker(get_default_limiter())
    except Exception as leaker_exc:
        _logger.warning("pyrate Leaker shutdown skipped: %s", leaker_exc)

    # ── 11. OTel metrics shutdown ──
    # Sprint 16 K2 W3 (L3-P0-1): graceful shutdown OTel MeterProvider.
    try:
        from src.backend.infrastructure.observability.otel import shutdown_otel_metrics

        shutdown_otel_metrics()
    except Exception as metrics_stop_exc:
        _logger.warning("OTel metrics shutdown skipped: %s", metrics_stop_exc)

    # ── 12. RedisClusterAdapter close ──
    cluster_adapter = getattr(app.state, "redis_cluster_adapter", None)
    if cluster_adapter is not None:
        try:
            await cluster_adapter.close()
        except Exception as rc_close_exc:
            _logger.warning("RedisClusterAdapter close error: %s", rc_close_exc)

    # ── 12b. EventBus stop (S133 W4) ──
    bus = getattr(app.state, "event_bus", None)
    if bus is not None:
        try:
            await bus.stop()
        except Exception as bus_stop_exc:
            _logger.warning("EventBus shutdown error: %s", bus_stop_exc)

    # ── 13. FeatureFlagBroadcaster stop ──
    # Sprint 17 K5 W1 (D9): graceful stop ДО task_registry.shutdown_all,
    # чтобы subscriber-task успел отписаться от Redis pub/sub корректно
    # (а не быть отменённым).
    bcast = getattr(app.state, "feature_flag_broadcaster", None)
    if bcast is not None:
        try:
            await bcast.stop()
        except Exception as bcast_stop_exc:
            _logger.warning("FeatureFlagBroadcaster shutdown error: %s", bcast_stop_exc)

    # ── 14. TaskRegistry graceful cancel ──
    # Sprint 1 V16 (R-V15-11): graceful cancel всех зарегистрированных
    # фоновых задач. Делается ПОСЛЕ ending()/log shutdown, чтобы тех
    # задачи, которые ещё могли логировать остановку, успели завершиться.
    try:
        await task_registry.shutdown_all(timeout=10)  # type: ignore[union-attr]
    except Exception as tr_exc:
        _logger.warning("TaskRegistry shutdown error: %s", tr_exc)
