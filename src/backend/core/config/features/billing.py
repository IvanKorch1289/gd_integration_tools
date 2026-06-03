"""Billing & extensions feature-flags (T1.3.11 split from core.config.features.__init__).

Извлечено 4 flags (S38 P1.1 W1 T1.3.11):
- Sprint 7 K1 per-tenant billing/quotas (3):
  - per_tenant_billing_enabled
  - supply_chain_finale_strict
  - openfeature_flagsmith_backend
- K9 — Extensions Migration (1):
  - extensions_core_entities
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class BillingFlags(BaseSettings):
    """Sprint 7 K1 per-tenant billing/quotas + K9 — Extensions. Owner: K1 Security, K9 Frontend&Ext.

    Per S38 T1.3.11, извлечено из monolithic ``core.config.features.FeatureFlags``.

    Re-export в ``__init__.py``:
        from src.backend.core.config.features.billing import BillingFlags
        class FeatureFlags(..., BillingFlags, ...):
            ...

    Env-var prefix: ``FEATURE_``.
    """

    model_config = SettingsConfigDict(env_prefix="FEATURE_", extra="forbid")

    per_tenant_billing_enabled: bool = Field(
        default=False,
        title="K1 S7: per-tenant billing/quotas (rpm/rpd/tokens/cost_usd)",
        description=(
            "K1 Sprint 7. Owner: K1 Security. ETA: S7. "
            "Активирует QuotasService (src/backend/services/billing/) и "
            "QuotaCheckMiddleware (src/backend/core/auth/quotas.py) — "
            "проверку per-tenant rpm/rpd/tokens/cost_usd на HTTP-уровне. "
            "При False сервис превращается в no-op (allowed=True для всех). "
            "default-OFF до интеграции с TenantContext + Redis backend и smoke."
        ),
    )

    supply_chain_finale_strict: bool = Field(
        default=False,
        title="K1 S7: supply-chain finale (cosign sign для SBOM+wheels+image)",
        description=(
            "K1 Sprint 7. Owner: K1 Security. ETA: S7. "
            "Активирует strict-режим supply-chain-finale в "
            "tools/checks/check_supply_chain.py — cosign-sign для всех "
            "release-артефактов (SBOM, dist/*.whl, container image при "
            "наличии docker buildx). default-OFF до проверки полного pipeline "
            "и signing keys readiness."
        ),
    )

    openfeature_flagsmith_backend: bool = Field(
        default=False,
        title="K1 S7: OpenFeature SDK через FlagsmithProvider (external)",
        description=(
            "K1 Sprint 7. Owner: K1 Security. ETA: S7. "
            "Активирует миграцию feature-flag backend с InMemoryProvider на "
            "external Flagsmith через core/feature_flags/openfeature_provider.py. "
            "Управляется ENV FEATURE_FLAG_BACKEND=flagsmith. При False — "
            "in-memory provider (поведение совпадает с локальным реестром). "
            "default-OFF до развёртывания Flagsmith instance в staging."
        ),
    )

    extensions_core_entities: bool = Field(
        default=False,
        title="Extensions: core_entities (users/orders/orderkinds/files) вынесен",
        description=(
            "K9 Wave 3. Owner: K9 Frontend&Ext. ETA: S2-W3. "
            "При True ядро НЕ регистрирует CRUD из extensions/core_entities/. "
            "default-OFF до golden-test migration + ядро без импортов."
        ),
    )


__all__ = ("BillingFlags",)
