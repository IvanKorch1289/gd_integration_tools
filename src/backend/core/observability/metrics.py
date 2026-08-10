"""Capability-checked facade для metrics registry (S120 W4).

ADR-0207: services/* observability (metrics.py, sla_alerting.py) импортируют
``metrics_registry`` из ``core.utils.metrics_registry``.
Этот facade переносит публичную поверхность в ``core.observability``.

Migration path:
- ``from src.backend.core.utils.metrics_registry import ...``
  → ``from src.backend.core.observability.metrics import ...``
"""

from __future__ import annotations

from src.backend.core.di.providers.infrastructure_locator import (
    get_default_labels_attr as _get_default_labels,
)
from src.backend.core.di.providers.infrastructure_locator import (
    get_metrics_registry_class as _get_metrics_registry_cls,
)
from src.backend.core.di.providers.infrastructure_locator import (
    get_metrics_registry_factory as _get_metrics_registry_fn,
)

DEFAULT_LABELS = _get_default_labels("DEFAULT_LABELS")
MetricsRegistry = _get_metrics_registry_cls()
metrics_registry = _get_metrics_registry_fn()

# B-06 fix (cycle 33): DLQ 3-stage fallback terminal metric.
# Инкрементируется только когда И Stage 1 (Redis stream) И Stage 2 (local
# JSONL) завершились ошибкой — терминальный сигнал полной потери DLQ-записи.
# Метка ``stage`` дискриминирует первичный отказ (``"primary"`` — JSONL не
# сконфигурирован, отказал только Redis) от вторичного (``"all"`` — оба
# этапа провалились). Используется алертингом для детекции loss-of-loss
# условий: рост counter'а = требуется немедленная эскалация (см. docs).
dlq_send_failed_total = metrics_registry.counter(
    "dlq_send_failed_total",
    "Total DLQ exchanges that failed at all stages (Redis stream + JSONL).",
    labels=("stage",),
)

# B-02 fix (cycle 33): Webhook signature middleware fail-closed counter.
# Инкрементируется на каждый запрос к protected path-prefix, для которого
# secret не сконфигурирован (т.е. ``_resolve_secret`` вернул ``None``).
# Метка ``path_prefix`` дискриминирует конкретный prefix, по которому
# пришёл запрос, чтобы алертинг мог точно локализовать misconfigured
# webhook endpoint. Используется для детекции drift между
# ``secrets_by_prefix`` (конфиг) и реально объявленными webhook-routes.
webhook_signature_missing_secret_total = metrics_registry.counter(
    "webhook_signature_missing_secret_total",
    "Webhook requests denied because no secret configured for path prefix.",
    labels=("path_prefix",),
)

# D-A3-02 fix (cycle 1): ClickHouse audit silent-loss counter.
# Инкрементируется в :meth:`ClickHouseAuditService._send_to_dlq` когда
# НИ canonical DLQWriter НИ legacy JSONL path не сконфигурированы —
# терминальный сигнал полной потери audit-события (production data-loss
# без наблюдаемости). Метка ``transport`` дискриминирует источник
# (по умолчанию ``clickhouse_audit``); метка ``reason`` — high-level
# причина (например ``no_dlq_configured``). Используется алертингом
# для детекции fail-OPEN условий.
audit_silent_loss_total = metrics_registry.counter(
    "audit_silent_loss_total",
    "Audit events lost without DLQ persistence (fail-OPEN path).",
    labels=("transport", "reason"),
)

__all__ = (
    "DEFAULT_LABELS",
    "MetricsRegistry",
    "audit_silent_loss_total",
    "dlq_send_failed_total",
    "metrics_registry",
    "webhook_signature_missing_secret_total",
)
