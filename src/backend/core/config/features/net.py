"""Net feature-flags (T1.3.5 split from core.config.features.__init__).

Извлечено 3 K2 — Net & WAF flags (S38 P1.1 epic, T1.3.5 PR):
- metering_per_host
- connection_reuse_manager
- waf_outbound_via_facade
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class NetFlags(BaseSettings):
    """K2 — Net & WAF. Owner: K2 Net&WAF, K2 Resilience.

    Per S38 T1.3.5, извлечено из monolithic ``core.config.features.FeatureFlags``
    для eventual multi-inheritance split (9 доменов, 10 PRs).

    Re-export в ``__init__.py``:
        from src.backend.core.config.features.net import NetFlags
        class FeatureFlags(AuthFlags, SecurityFlags, ObservabilityFlags, NetFlags, ...):
            ...

    Env-var prefix: ``FEATURE_`` (inherited from parent pydantic-settings config).
    """

    model_config = SettingsConfigDict(env_prefix="FEATURE_", extra="forbid")

    metering_per_host: bool = Field(
        default=True,
        title="K2: per-host outbound metering (request_count, error_rate, p50/p95)",
        description=(
            "K2 Wave 1. Owner: K2 Net&WAF. ETA: S3-W1. "
            "Активирует PerHostMeter — rolling-window (1000 obs) метрики "
            "по каждому host: request_count, error_count, p50/p95 latency_ms. "
            "default-OFF до staging-smoke и интеграции с OutboundHttpClient."
        ),
    )

    connection_reuse_manager: bool = Field(
        default=True,
        title="K2: ConnectionReuseManager (idle ping + auto-recycle по lifetime)",
        description=(
            "K2 Wave 2. Owner: K2 Resilience. ETA: S3-W2. "
            "Активирует ConnectionReuseManager: проверку lifetime и idle-ping "
            "перед возвратом connection из pool. При False acquire() возвращает "
            "pool-объект без дополнительных проверок (нулевой overhead). "
            "default-OFF до интеграции в reference pools и staging-smoke."
        ),
    )

    waf_outbound_via_facade: bool = Field(
        default=True,
        title="WAF: внешние HTTP через OutboundHttpClient",
        description=(
            "K2 Wave 3. Owner: K2 Net&WAF. ETA: S2-W2. "
            "Маршрутизация всех :external HTTP-callsites через WAF-фасад. "
            "default-OFF до завершения миграции 38 callsites и staging-smoke. "
            "Переключение default-ON — отдельный PR после ADR-0053 Accepted."
        ),
    )


__all__ = ("NetFlags",)
