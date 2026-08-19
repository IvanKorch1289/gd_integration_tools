"""Billing domain provider — :class:`QuotasBackend` registration (cycle 33).

B-07 fix (cycle 33): DI-провайдер для billing backend. По умолчанию
возвращает :class:`services.billing.NoOpBillingFacade` (real billing
backend not yet integrated). При включённом feature-flag
``BILLING_ENABLED=True`` бросает :class:`NotImplementedError` — это
защищает от silent-fallback на no-op в проде, когда реальный backend
ещё не готов.

Override через :func:`set_quotas_backend_provider` для test-инжекции.
"""

from __future__ import annotations

from typing import Any

# Lazy import для предотвращения core→services layer-violation:
# `core/di/providers/billing.py` (core) → `services/billing/no_op_billing.py` (services)
# запрещён `tools/check_layers.py`. Lazy import внутри функции (как `cdc_bridge.py`)
# допустим. B-07 follow-up (cycle 33): исправление FAIL-1 Phase-5 ревью.

_overrides: dict[str, Any] = {}


def get_quotas_backend_provider() -> Any:
    """Возвращает singleton :class:`QuotasBackend`.

    B-07 fix (cycle 33): возвращает :class:`NoOpBillingFacade` пока реальный
    backend не интегрирован. При :data:`BILLING_ENABLED`=True —
    :class:`NotImplementedError` (fail-loud вместо silent no-op).

    Override через :func:`set_quotas_backend_provider` имеет приоритет.

    Returns:
        Реализация :class:`core.auth.quotas_protocol.QuotasBackend`.

    Raises:
        NotImplementedError: Если ``BILLING_ENABLED=True`` и не задан override.

    """
    if "quotas_backend" in _overrides:
        return _overrides["quotas_backend"]
    # Lazy import: prevents core→services layer-violation (FAIL-1 cycle 33).
    from src.backend.services.billing import no_op_billing

    if no_op_billing.BILLING_ENABLED:
        raise NotImplementedError(
            "billing_enabled=True but real billing backend not yet integrated. "
            "Use set_quotas_backend_provider(...) for test override or set "
            "BILLING_ENABLED=False (default) until QuotasService ships."
        )
    return no_op_billing.NoOpBillingFacade()


def set_quotas_backend_provider(impl: Any) -> None:
    """Установить/сбросить override для ``quotas_backend`` provider (test-инжекция).

    ``None`` сбрасывает override и возвращает к default (NoOpBillingFacade
    или NotImplementedError в зависимости от :data:`BILLING_ENABLED`).
    """
    if impl is None:
        _overrides.pop("quotas_backend", None)
    else:
        _overrides["quotas_backend"] = impl


__all__ = ("get_quotas_backend_provider", "set_quotas_backend_provider")
