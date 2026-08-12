"""Observability feature-flags (T1.3.4 split from core.config.features.__init__).

Извлечено 3 fields из 2 sections (S38 P1.1 epic, T1.3.4 PR; B-series 2026-08):
- K1 — Tracing & Observability: tracing_baggage_strict
- K8 — Audit & ClickHouse: audit_clickhouse_enabled, audit_hmac_verify_enabled
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ObservabilityFlags(BaseSettings):
    """K1 — Tracing + K8 — Audit. Owner: K1 Auth/Tracing, K8 Audit.

    Per S38 T1.3.4, извлечено из monolithic ``core.config.features.FeatureFlags``
    для eventual multi-inheritance split (9 доменов, 10 PRs).

    Re-export в ``__init__.py``:
        from src.backend.core.config.features.observability import ObservabilityFlags
        class FeatureFlags(AuthFlags, SecurityFlags, ObservabilityFlags, ...):
            ...

    Env-var prefix: ``FEATURE_`` (inherited from parent pydantic-settings config).
    """

    model_config = SettingsConfigDict(env_prefix="FEATURE_", extra="forbid")

    tracing_baggage_strict: bool = Field(
        default=True,
        title="Tracing: strict-режим проверки OTel baggage (все 4 поля обязательны)",
        description=(
            "K1 Wave 2. Owner: K1 Auth/Tracing. ETA: S3-W2. "
            "При True вызов ensure_required_baggage() возбуждает MissingBaggageError, "
            "если хотя бы одно из 4 полей (route_name/tenant_id/business_op/correlation_id) "
            "отсутствует в OTel baggage context. "
            "default-OFF до покрытия всех entrypoints propagation middleware и staging-smoke."
        ),
    )

    audit_clickhouse_enabled: bool = Field(
        default=True,
        title="Audit: ClickHouse audit_events trail",
        description=(
            "K8 Wave 4. Owner: K8 Audit. ETA: S2-W4. "
            "Активирует отправку audit-событий в ClickHouse (таблица audit_events). "
            "При False — ClickHouseAuditService пропускает emit/emit_batch без ошибок. "
            "default-OFF до запуска ClickHouse instance и smoke-теста в staging."
        ),
    )

    audit_hmac_verify_enabled: bool = Field(
        default=False,
        title="Audit: periodic HMAC-chain verify (tamper detection)",
        description=(
            "B-series 2026-08-03. Owner: K8 Audit. "
            "Активирует периодический вызов :meth:`ImmutableAuditStore.verify` "
            "через :mod:`audit_verify_lifecycle` (default интервал 24h). "
            "Opt-in (default False) — dev/dev_light не должны поднимать Postgres "
            "audit_log_immutable таблицу только ради verify-цикла; в prod "
            "выставляется через env ``FEATURE_AUDIT_HMAC_VERIFY_ENABLED=true``."
        ),
    )


__all__ = ("ObservabilityFlags",)
