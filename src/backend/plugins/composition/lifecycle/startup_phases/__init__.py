"""Sprint 15 P1-12: extracted startup phases из `startup.py` (584 → thin orchestrator).

Каждая фаза — async функция с сигнатурой ``async def _phase_*(app: FastAPI) -> None``.
Оркестратор (``startup.run_startup``) итерирует список фаз в порядке зависимостей.

Группировка:
- :mod:`observability` — OTel, Sentry, LogSink, Audit HMAC, ConfigValidator
- :mod:`infrastructure` — Redis cluster, setup_infra, EventBus
- :mod:`services` — Service registration, AIGateway, DSL, PluginLoader, V11, Outbox, Workflow, Schema, FeatureFlag

Принцип: best-effort startup (hard errors propagate, optional subsystems log+continue).
Каждая фаза оборачивает свой critical path в try/except с понятным warning.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import FastAPI

from src.backend.plugins.composition.lifecycle.startup_phases import (
    infrastructure,
    observability,
    services,
)

Phase = Callable[[FastAPI], Awaitable[None]]

# Ordered list — выполнение строго sequential, в documented order.
STARTUP_PHASES: tuple[Phase, ...] = (
    # Observability baseline (5 phases)
    observability.phase_otel_traces,
    observability.phase_otel_metrics,
    observability.phase_config_validator,
    observability.phase_sentry_init,
    observability.phase_logsink_router,
    observability.phase_audit_hmac_verify,
    # Infrastructure (3 phases)
    infrastructure.phase_redis_cluster,
    infrastructure.phase_setup_infra,
    infrastructure.phase_eventbus_startup,
    # Services (10 phases)
    services.phase_service_registration,
    services.phase_ai_gateway_singleton,
    services.phase_dsl_commands,
    services.phase_watchers,
    services.phase_plugin_loader,
    services.phase_v11_loaders,
    services.phase_outbox_dispatcher,
    services.phase_workflow_runtime,
    services.phase_schema_registry,
    services.phase_feature_flag_broadcaster,
)


__all__ = ("Phase", "STARTUP_PHASES")
