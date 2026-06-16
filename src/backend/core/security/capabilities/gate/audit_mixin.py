from __future__ import annotations

from src.backend.core.security.capabilities.gate._protocol import (
    _CapabilityGateProtocol,
)

"""ADR-044 — runtime :class:`CapabilityGate` + subset-checker.

Plugin/route декларирует свои capabilities при load; gate проверяет
каждый запрос ресурса на runtime через ``check(...)`` с LRU-кэшем.

Subset-проверка (route ⊆ plugins ∪ core_public) реализована статически
в :func:`check_capabilities_subset` и используется RouteLoader'ом до
активации маршрута.

Sprint 36 (V15 GAP, Subagent A) additions:

* Optional ``policy: CapabilityPolicy`` в ``__init__`` — consult policy
  *before* declaration-check; deny/allow/no_match semantics с tie-break
  deny > allow.
* Tenant-aware API: :meth:`check_tenant`, :meth:`declare_tenant`,
  :meth:`revoke_tenant`, :meth:`list_allocated_tenant` (per-tenant
  LRU cache, audit events ``capability.allocated`` /
  ``capability.revoked``).
* Default tenant = :data:`SYSTEM_TENANT_ID` (``"_system"``) — backward
  compat с existing call sites.
"""

from collections.abc import Callable
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    pass

AuditCallback = Callable[[dict[str, object]], None]
"""Подпись audit-callback'а: принимает event dict, ничего не возвращает."""

_DEFAULT_LRU_SIZE: Final[int] = 1024


class AuditMixin(_CapabilityGateProtocol):
    """audit event emission для CapabilityGate. S54 W4 extraction."""

    __slots__ = ()

    def _emit_audit(
        self,
        *,
        plugin: str,
        capability: str,
        requested_scope: str | None,
        declared_scope: str | None,
        outcome: str,
        tenant: str | None = None,
        reason: str | None = None,
        event: str = "capability.check",
    ) -> None:
        """Вызвать audit-callback, если задан.

        S106 W5 closure: дополнительно вызывает
        ``emit_capability_check`` helper из ``core.audit.facade`` (S106 W2
        Path A) для dual-emission: callback для backward compat + unified
        audit service для новых консумеров. 17 inherited callsites
        автоматически получают новый path.

        Поля ``tenant``, ``reason``, ``event`` — опциональные
        (передаются только в tenant-aware путях или для указания
        причины ``"policy"``). Старые callers (без этих kwargs) получают
        тот же event-dict, что и раньше — backward compat preserved.
        """
        if self._audit is not None:
            payload: dict[str, object] = {
                "event": event,
                "plugin": plugin,
                "capability": capability,
                "requested_scope": requested_scope,
                "declared_scope": declared_scope,
                "outcome": outcome,
            }
            if tenant is not None:
                payload["tenant"] = tenant
            if reason is not None:
                payload["reason"] = reason
            self._audit(payload)

        # S106 W5: dual emission через unified audit service.
        # Lazy import для избежания circular dep (facade → services/audit).
        from src.backend.core.audit.facade import emit_capability_check

        emit_capability_check(
            plugin=plugin,
            capability=capability,
            requested_scope=requested_scope,
            declared_scope=declared_scope,
            outcome=outcome,
            tenant=tenant,
            reason=reason,
            event=event,
        )
