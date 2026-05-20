"""Protocol-контракт quotas backend (Sprint 11 S10-carryover/layer-violations-zero).

Отделяет публичные dataclass-результаты от реализации в
``services/billing/quotas_service.py``. ``core/auth/quotas.py``
зависит только от этих типов и Protocol-интерфейса, не от services.

Импл-сервис (`QuotasService`) реализует :class:`QuotasBackend`
структурно (Python duck-typing) и регистрируется в DI-контейнере.
``QuotaCheckResult`` / ``QuotaUsage`` объявлены структурно как
:class:`Protocol`, чтобы существующие dataclass-реализации в
services/billing продолжали удовлетворять контракту без изменений.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

__all__ = (
    "QuotaCheckResult",
    "QuotaUsage",
    "QuotasBackend",
)


@runtime_checkable
class QuotaUsage(Protocol):
    """Контракт снимка текущего потребления per-tenant."""

    tenant_id: str
    requests_in_minute: int
    requests_in_day: int
    cost_in_day_usd: float
    reset_minute_at: int
    reset_day_at: int


@runtime_checkable
class QuotaCheckResult(Protocol):
    """Контракт результата одной проверки квоты."""

    allowed: bool
    reason: str
    usage: QuotaUsage


@runtime_checkable
class QuotasBackend(Protocol):
    """Контракт quotas-backend для core/auth middleware.

    Реализуется :class:`services.billing.quotas_service.QuotasService`.
    Только методы, нужные ASGI-middleware и REST-фасадам.
    """

    async def consume_request(self, tenant_id: str) -> QuotaCheckResult:
        """Зафиксировать один входящий запрос и проверить лимиты."""
        ...

    async def check_tokens(self, tenant_id: str, tokens: int) -> QuotaCheckResult:
        """Проверить лимит токенов до фактического вызова LLM."""
        ...
