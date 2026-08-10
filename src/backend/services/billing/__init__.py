"""Billing services package — placeholder для QuotasBackend.

Cycle 33 B-07 fix: stub → :class:`NoOpBillingFacade` (real billing backend
not yet integrated). При ``BILLING_ENABLED=False`` (default) фасад
возвращает ``allowed=True`` и эмитит audit-event ``quota_check_skipped``.
При ``BILLING_ENABLED=True`` — :class:`NotImplementedError`.

См. также:

* :mod:`src.backend.services.billing.no_op_billing` — no-op фасад.
* :mod:`src.backend.services.billing.quotas_service` — stub скелет.
* :mod:`src.backend.core.di.providers.billing` — DI provider.
* :class:`src.backend.core.auth.quotas_protocol.QuotasBackend` — контракт.
"""

from __future__ import annotations as annotations

from src.backend.services.billing.no_op_billing import (
    BILLING_ENABLED,
    NoOpBillingFacade,
)
from src.backend.services.billing.quotas_service import (
    QuotasService,
)

__all__ = ("BILLING_ENABLED", "NoOpBillingFacade", "QuotasService")
