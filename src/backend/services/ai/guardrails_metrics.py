"""Guardrails metrics service (Sprint 9 K4 W5 — GAP-AI-3.8).

Аггрегирует метрики AI Safety guardrails:

* блокированные prompts / completions (по причине: PII / toxic / off-topic);
* false-positive rate (manual review labeled);
* per-tenant breakdown.

Используется страницей ``47_AI_Safety.py`` для dashboard, а также
Prometheus exporter (``guardrails_metrics``).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from src.backend.core.logging import get_logger

__all__ = (
    "GuardrailMetrics",
    "GuardrailReason",
    "GuardrailVerdict",
    "GuardrailsMetricsService",
)

logger = get_logger("services.ai.guardrails_metrics")


class GuardrailVerdict(StrEnum):
    ALLOW = "allow"
    BLOCK = "block"
    REDACT = "redact"


class GuardrailReason(StrEnum):
    PII = "pii"
    TOXIC = "toxic"
    OFF_TOPIC = "off_topic"
    JAILBREAK = "jailbreak"
    PROMPT_INJECTION = "prompt_injection"
    COST_OVER = "cost_over"
    OTHER = "other"


@dataclass(slots=True)
class GuardrailMetrics:
    """Per-tenant per-period snapshot.

    Attributes:
        tenant_id: tenant.
        total: всего guardrail-проверок за период.
        allow: разрешённых.
        block: блокированных.
        redact: пропущенных с redaction (PII masking).
        by_reason: ``reason → count``.
        false_positives: manual-labeled FP (после operator review).
    """

    tenant_id: str
    total: int = 0
    allow: int = 0
    block: int = 0
    redact: int = 0
    by_reason: dict[str, int] = field(default_factory=dict)
    false_positives: int = 0

    @property
    def block_rate(self) -> float:
        """Get block rate as ratio.

        Returns:
            Block rate (0.0 to 1.0).
        """
        return self.block / self.total if self.total else 0.0

    @property
    def false_positive_rate(self) -> float:
        """Get false positive rate as ratio.

        Returns:
            False positive rate (0.0 to 1.0).
        """
        return self.false_positives / self.block if self.block else 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert metrics to dictionary.

        Returns:
            Dictionary representation.
        """
        return {
            "tenant_id": self.tenant_id,
            "total": self.total,
            "allow": self.allow,
            "block": self.block,
            "redact": self.redact,
            "by_reason": self.by_reason,
            "false_positives": self.false_positives,
            "block_rate": self.block_rate,
            "false_positive_rate": self.false_positive_rate,
        }


class GuardrailsMetricsService:
    """In-memory + ClickHouse aggregator (Sprint 9 K4 W5 → S28 W8).

    In-memory aggregation supports Prometheus scraping and real-time dashboards.
    ClickHouse bulk writer (if provided) persists every guardrail check to
    ``guardrail_events`` table for long-term analytics.

    ClickHouse table schema:

    .. code-block:: sql

        CREATE TABLE IF NOT EXISTS guardrail_events (
            tenant_id     String,
            verdict       Enum8('allow'=1, 'block'=2, 'redact'=3),
            reason        String,
            model_used    String,
            cost_usd      Float64,
            latency_ms    Float32,
            timestamp     DateTime64(3) DEFAULT now64(3)
        ) ENGINE = MergeTree()
        ORDER BY (tenant_id, timestamp);
    """

    def __init__(
        self,
        *,
        clickhouse_writer: Any = None,  # ClickHouseBulkWriter | None
    ) -> None:
        self._by_tenant: dict[str, GuardrailMetrics] = {}
        self._lock = asyncio.Lock()
        self._ch_writer = clickhouse_writer  # bulk writer, may be None

    async def record(
        self,
        *,
        tenant_id: str,
        verdict: GuardrailVerdict,
        reason: GuardrailReason | None = None,
        model_used: str = "unknown",
        cost_usd: float = 0.0,
        latency_ms: float = 0.0,
    ) -> None:
        """Зарегистрировать одну guardrail-проверку.

        Writes to both in-memory aggregation (for Prometheus) and
        ClickHouse (for analytics). ClickHouse errors are logged but
        do not affect the in-memory state.
        """
        async with self._lock:
            metrics = self._by_tenant.setdefault(
                tenant_id, GuardrailMetrics(tenant_id=tenant_id)
            )
            metrics.total += 1
            if verdict == GuardrailVerdict.ALLOW:
                metrics.allow += 1
            elif verdict == GuardrailVerdict.BLOCK:
                metrics.block += 1
            elif verdict == GuardrailVerdict.REDACT:
                metrics.redact += 1
            if reason is not None:
                metrics.by_reason[reason.value] = (
                    metrics.by_reason.get(reason.value, 0) + 1
                )

        # ClickHouse persistence — fire-and-forget, errors logged but non-fatal
        if self._ch_writer is not None:
            try:
                self._ch_writer.add(
                    {
                        "tenant_id": tenant_id,
                        "verdict": verdict.value,
                        "reason": reason.value if reason else "other",
                        "model_used": model_used,
                        "cost_usd": cost_usd,
                        "latency_ms": latency_ms,
                    }
                )
            except Exception as exc:
                logger.debug("GuardrailsMetrics CH write failed: %s", exc)

    async def mark_false_positive(self, *, tenant_id: str, count: int = 1) -> None:
        """Mark operator-labeled false positives.

        Args:
            tenant_id: Tenant identifier.
            count: Number of false positives.
        """
        async with self._lock:
            metrics = self._by_tenant.setdefault(
                tenant_id, GuardrailMetrics(tenant_id=tenant_id)
            )
            metrics.false_positives += count

    async def snapshot(self, tenant_id: str) -> GuardrailMetrics:
        """Get metrics snapshot for a tenant.

        Args:
            tenant_id: Tenant identifier.

        Returns:
            GuardrailMetrics for the tenant.
        """
        async with self._lock:
            return self._by_tenant.get(tenant_id, GuardrailMetrics(tenant_id=tenant_id))

    async def list_all(self) -> list[GuardrailMetrics]:
        """List metrics for all tenants.

        Returns:
            List of GuardrailMetrics sorted by tenant_id.
        """
        async with self._lock:
            return sorted(self._by_tenant.values(), key=lambda m: m.tenant_id)

    async def reset(self, tenant_id: str | None = None) -> None:
        """Admin-action: сбросить (per-tenant или всё)."""
        async with self._lock:
            if tenant_id is None:
                self._by_tenant.clear()
            else:
                self._by_tenant.pop(tenant_id, None)
