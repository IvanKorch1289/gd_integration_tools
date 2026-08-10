"""No-op BillingFacade — placeholder для :class:`QuotasBackend` (cycle 33).

B-07 fix (cycle 33): ``services/billing`` stub заменён на no-op фасад.
Структурно реализует :class:`core.auth.quotas_protocol.QuotasBackend`,
возвращает ``QuotaCheckResult(allowed=True, reason='billing_not_configured')``
и эмитит audit-event ``quota_check_skipped`` через
:func:`core.audit.facade.audit_service.emit`.

Поведение управляется module-флагом :data:`BILLING_ENABLED` (default ``False``):

* ``BILLING_ENABLED=False`` (default): no-op, все запросы allowed=True.
* ``BILLING_ENABLED=True``: :class:`NotImplementedError` — реальный backend
  ещё не интегрирован; используйте default до тех пор, пока QuotasService
  не появится в ``services/billing/quotas_service.py``.

Контракт соответствует :class:`QuotasBackend` Protocol (см.
``core/auth/quotas_protocol.py``) — изолирует :class:`QuotaCheckMiddleware`
от конкретной реализации billing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.backend.core.auth.quotas_protocol import (
    QuotaCheckResult,
    QuotasBackend,
    QuotaUsage,
)
from src.backend.core.logging import get_logger

__all__ = ("BILLING_ENABLED", "NoOpBillingFacade")

_logger = get_logger("services.billing.no_op")

# Feature-flag контролирует выбор backend'а. По умолчанию OFF — реальный
# billing backend не интегрирован, фасад возвращает allowed=True без счётчиков.
# При BILLING_ENABLED=True — DI-провайдер бросает NotImplementedError, чтобы
# избежать silent-fallback на no-op в проде.
BILLING_ENABLED: bool = False


@dataclass(slots=True)
class _NoOpUsage:
    """Структурный снимок потребления (нулевые счётчики)."""

    tenant_id: str
    requests_in_minute: int = 0
    requests_in_day: int = 0
    cost_in_day_usd: float = 0.0
    reset_minute_at: int = 0
    reset_day_at: int = 0


@dataclass(slots=True)
class _NoOpResult:
    """Структурный результат проверки квоты (always allowed)."""

    allowed: bool
    reason: str
    usage: QuotaUsage


class NoOpBillingFacade:
    """No-op BillingFacade: разрешает всё, эмитит audit-event.

    B-07 fix (cycle 33): stub → no-op BillingFacade с audit event.

    Реализует :class:`QuotasBackend` структурно (duck typing). Используется
    как default в :mod:`core.di.providers.billing`, пока не появится реальный
    backend. Каждый вызов :meth:`consume_request` / :meth:`check_tokens`
    эмитит audit-event ``quota_check_skipped`` (best-effort, без raise —
    audit не должен ломать бизнес-логику).
    """

    __slots__ = ()

    async def consume_request(self, tenant_id: str) -> QuotaCheckResult:
        """Зафиксировать входящий запрос, вернуть allowed=True + audit-event.

        Args:
            tenant_id: Идентификатор арендатора.

        Returns:
            :class:`QuotaCheckResult` с ``allowed=True`` и
            ``reason='billing_not_configured'``.

        Raises:
            NotImplementedError: Если :data:`BILLING_ENABLED` истинно —
                реальный backend не интегрирован.
        """
        _ensure_disabled_or_raise()
        await _emit_quota_check_skipped(tenant_id, method="consume_request")
        return _NoOpResult(
            allowed=True,
            reason="billing_not_configured",
            usage=_NoOpUsage(tenant_id=tenant_id),
        )

    async def check_tokens(self, tenant_id: str, tokens: int) -> QuotaCheckResult:
        """Проверить лимит токенов (no-op returns allowed=True).

        Args:
            tenant_id: Идентификатор арендатора.
            tokens: Запрашиваемое количество токенов.

        Returns:
            :class:`QuotaCheckResult` с ``allowed=True``.

        Raises:
            NotImplementedError: Если :data:`BILLING_ENABLED` истинно.
        """
        _ensure_disabled_or_raise()
        await _emit_quota_check_skipped(
            tenant_id, method="check_tokens", tokens=tokens
        )
        return _NoOpResult(
            allowed=True,
            reason="billing_not_configured",
            usage=_NoOpUsage(tenant_id=tenant_id),
        )


def _ensure_disabled_or_raise() -> None:
    """Бросить ``NotImplementedError``, если :data:`BILLING_ENABLED` включён."""
    if BILLING_ENABLED:
        raise NotImplementedError(
            "billing_enabled=True but real billing backend not yet integrated. "
            "Set BILLING_ENABLED=False (default) until QuotasService ships."
        )


async def _emit_quota_check_skipped(
    tenant_id: str, *, method: str, tokens: int | None = None
) -> None:
    """Эмитит audit-event ``quota_check_skipped`` через :class:`AuditService`.

    Best-effort: ошибка audit не должна ломать consume_request/check_tokens
    (audit не на пути бизнес-логики). При недоступности backend'а —
    WARNING-лог, drop.
    """
    details: dict[str, Any] = {
        "facade": "no_op",
        "tenant_id": tenant_id,
        "method": method,
        "reason": "billing_not_configured",
    }
    if tokens is not None:
        details["tokens"] = tokens
    try:
        from src.backend.core.audit.facade.audit_service import (
            get_unified_audit_service,
        )

        audit = get_unified_audit_service()
        await audit.emit(
            event="quota_check_skipped",
            actor="system",
            resource=f"tenant/{tenant_id}",
            action="quota_check",
            outcome="success",
            severity="info",
            tenant_id=tenant_id,
            details=details,
        )
    except Exception as exc:  # pragma: no cover — audit is best-effort
        _logger.warning(
            "billing.no_op.audit_emit_failed",
            extra={"tenant_id": tenant_id, "method": method, "error": repr(exc)},
        )


# Structural typing self-check (development aid; not enforced at import time).
# ``isinstance(NoOpBillingFacade(), QuotasBackend)`` is True by duck typing.
if __name__ != "__main__":  # pragma: no cover
    _ = (NoOpBillingFacade, QuotasBackend)
