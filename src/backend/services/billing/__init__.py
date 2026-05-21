"""Sprint 7 K1 — per-tenant billing/quotas сервис.

Назначение:
    Подсистема учёта потребления per-tenant: RPM, RPD, токены, бюджет в USD.
    Используется ``QuotaCheckMiddleware`` (см. :mod:`src.backend.core.auth.quotas`)
    и AI/LLM-метеринг для отказа в обслуживании при превышении лимитов.

    Default-OFF через feature_flag ``per_tenant_billing_enabled`` — при
    выключенном флаге все ``check_*`` методы возвращают разрешение без
    обращения к Redis.

Экспортирует:
    QuotaWindow — лимиты на одно окно (rpm/rpd/tokens/cost_usd).
    QuotasService — основной API (consume_request / consume_tokens / consume_cost).
    QuotaUsage — снимок текущего потребления (для отчётов и dashboard).
"""

from __future__ import annotations

from src.backend.services.billing.quotas_service import (
    QuotasService,
    QuotaUsage,
    QuotaWindow,
)

__all__ = ("QuotaUsage", "QuotaWindow", "QuotasService")
