"""Sprint 5 security feature-flags (T1.3.12 split from core.config.features.__init__).

Извлечено 4 flags (S38 P1.1 W1 T1.3.12):
- Sprint 5 K1 Security (3):
  - supply_chain_ci_gate (K1 Wave 3)
  - dlq_replay_rbac (Sprint 5 K1 W4)
  - inbox_audit_pii_mask (Sprint 5 K1 W5)
- Sprint 5 K2 Resilience+Perf (1):
  - dlq_unified_enabled (Sprint 5 K2 W2)
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Sprint5Flags(BaseSettings):
    """Sprint 5 K1 Security + K2 Resilience. Owner: K1 Security, K2 Resilience.

    Per S38 T1.3.12, извлечено из monolithic ``core.config.features.FeatureFlags``.

    Re-export в ``__init__.py``:
        from src.backend.core.config.features.sprint5 import Sprint5Flags
        class FeatureFlags(..., Sprint5Flags, ...):
            ...

    Env-var prefix: ``FEATURE_``.
    """

    model_config = SettingsConfigDict(env_prefix="FEATURE_", extra="forbid")

    supply_chain_ci_gate: bool = Field(
        default=True,
        title="K1: Supply-chain CI gate (SBOM + pip-audit + cosign)",
        description=(
            "K1 Wave 3. Owner: K1 Auth/Secrets. ETA: S3-W3. "
            "Активирует обязательные supply-chain проверки в release pipeline: "
            "CycloneDX SBOM генерация, pip-audit vulnerability scan, "
            "cosign artifact signing. При False — gates пропускаются (warn-only). "
            "default-OFF до Sprint 4 release-pipeline интеграции (BLOCKER #4)."
        ),
    )

    dlq_replay_rbac: bool = Field(
        default=True,
        title="K1 S5 W4: DLQ replay endpoint @require_role admin + audit-event",
        description=(
            "K1 Sprint 5 Wave 4. Owner: K1 Security. ETA: S5-W4. "
            "Активирует RBAC-проверку для /api/v1/admin/dlq/replay endpoint: "
            "@require_role('admin') + audit-event + @capability_guarded. "
            "default-OFF до интеграции с CasbinAuthorizationService и smoke-теста."
        ),
    )

    inbox_audit_pii_mask: bool = Field(
        default=True,
        title="K1 S5 W5: Inbox dedup audit с PII masking через presidio",
        description=(
            "K1 Sprint 5 Wave 5. Owner: K1 Security. ETA: S5-W5. "
            "Активирует PII-маскировку (presidio) для audit-записей Inbox dedup. "
            "default-OFF до интеграции с PresidioAnalyzer и audit_events."
        ),
    )

    dlq_unified_enabled: bool = Field(
        default=True,
        title="K2 S5 W2: DLQ transport-agnostic facade + Postgres dlq_events",
        description=(
            "K2 Sprint 5 Wave 2. Owner: K2 Resilience. ETA: S5-W2. "
            "Активирует UnifiedDeadLetterQueue (core/messaging/dlq.py) + "
            "Postgres-table dlq_events(transport,action,payload,error,...) + "
            "REST /api/v1/admin/dlq/replay + DSL .dlq(target,max_attempts). "
            "default-OFF до миграции существующих transport-specific DLQ."
        ),
    )


__all__ = ("Sprint5Flags",)
