"""Resilience feature-flags (T1.3.10 split from core.config.features.__init__).

Извлечено 6 flags из K3 — Resilience & Scaling section (S38 P1.1 W1 T1.3.10):
- auto_scaler_process_level
- auto_scaler_task_level
- k8s_hpa_exporter
- otel_asyncpg
- task_watchdog_deadline
- pool_health_monitor (K8 Storage sub-section, kept here для cohesion)

Extension to original 9-domain T1.3.x plan.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ResilienceFlags(BaseSettings):
    """K3 — Resilience + K8 Storage. Owner: K3 Resilience, K8 Storage, K2 Net&WAF.

    Per S38 T1.3.10, извлечено из monolithic ``core.config.features.FeatureFlags``
    для eventual multi-inheritance split (continues T1.3.1-T1.3.9 pattern).

    Re-export в ``__init__.py``:
        from src.backend.core.config.features.resilience import ResilienceFlags
        class FeatureFlags(..., ResilienceFlags, ...):
            ...

    Env-var prefix: ``FEATURE_`` (inherited from parent pydantic-settings config).
    """

    model_config = SettingsConfigDict(env_prefix="FEATURE_", extra="forbid")

    k8s_hpa_exporter: bool = Field(
        default=False,
        title="K2: Prometheus k8s HPA exporter (container-level auto-scaler)",
        description=(
            "K2 Wave 4. Owner: K2 Net&WAF. ETA: S3-W4. "
            "Активирует K8sHPAMetricsExporter — уровень 3 auto-scaler (R-V15-10). "
            "Экспортирует метрики в Prometheus-text формате через GET /metrics/hpa. "
            "default-OFF до интеграции с k8s HPA и staging-smoke."
        ),
    )

    otel_asyncpg: bool = Field(
        default=False,
        title="Resilience: OTel auto-instrumentation для asyncpg",
        description=(
            "K3 Wave 1. Owner: K3 Resilience. ETA: S2-W1. "
            "Активирует opentelemetry-instrumentation-asyncpg. "
            "default-OFF до перформанс-baseline diff <5%."
        ),
    )

    task_watchdog_deadline: bool = Field(
        default=False,
        title="Resilience: TaskWatchdog deadline-эскалация для asyncio-задач",
        description=(
            "K3 Wave 2. Owner: K3 Resilience. ETA: S2-W2. "
            "Активирует TaskWatchdog: регистрация задач с deadline_seconds + "
            "auto-cancel при превышении. default-OFF до chaos-теста с leak-detection."
        ),
    )

    pool_health_monitor: bool = Field(
        default=False,
        title="Storage: ConnectionPoolHealthMonitor (idle ping + reuse-on-demand)",
        description=(
            "K8 Wave 5. Owner: K8 Storage. ETA: S2-W5. "
            "Активирует фоновый health-monitor для DB/Redis/HTTP/ClickHouse pools. "
            "default-OFF до интеграции в 4 reference pools."
        ),
    )


__all__ = ("ResilienceFlags",)
