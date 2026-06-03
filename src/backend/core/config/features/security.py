"""Security feature-flags (T1.3.2 split from core.config.features.__init__).

Извлечено 1 K1 — Secrets & Vault flag (S38 P1.1 epic, T1.3.2 PR).
Pattern: each domain имеет свой ``<Domain>Flags(BaseSettings)`` subclass.
``__init__.py`` композит их через multiple inheritance в единый ``FeatureFlags``.

Future T1.3.2.5+ extensions (deferred to S39+):
- ai_pii_tokenizer_enabled (S25 W4, K1 PII adjacent)
- supply_chain_ci_gate (K1 Auth/Secrets, S3-W3)
- Sprint 5/6 K1 Security fields (~10)
- Sprint 7 K1 per-tenant billing/quotas (3)
- Sprint 7 T5 OpenFeature provider (1)
- K1 — Plugin semver (1)
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class SecurityFlags(BaseSettings):
    """K1 — Secrets & Vault (Wave 1). Owner: K1 Auth/Secrets.

    Per S38 T1.3.2, извлечено из monolithic ``core.config.features.FeatureFlags``
    для eventual multi-inheritance split (9 доменов, 10 PRs).

    Re-export в ``__init__.py``:
        from src.backend.core.config.features.security import SecurityFlags
        class FeatureFlags(AuthFlags, SecurityFlags, ...):
            ...

    Env-var prefix: ``FEATURE_`` (inherited from parent pydantic-settings config).
    """

    model_config = SettingsConfigDict(env_prefix="FEATURE_", extra="forbid")

    vault_rotation_enabled: bool = Field(
        default=False,
        title="Secrets: scheduled Vault secret rotation hook (без рестарта)",
        description=(
            "K1 Wave 1. Owner: K1 Auth/Secrets. ETA: S3-W1. "
            "Активирует VaultSecretRotator — фоновую задачу, периодически "
            "перечитывающую Vault paths и обновляющую in-memory cache. "
            "default-OFF до integration-test с реальным Vault в staging."
        ),
    )


__all__ = ("SecurityFlags",)
