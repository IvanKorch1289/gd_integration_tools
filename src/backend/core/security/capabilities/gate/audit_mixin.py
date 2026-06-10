from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass  # cross-mixin / state attrs declared below

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

from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, Final

from src.backend.core.security.capabilities.errors import (
    CapabilityDeniedError,
    CapabilityNotFoundError,
    CapabilitySupersetError,
)
from src.backend.core.security.capabilities.models import CapabilityRef
from src.backend.core.security.capabilities.tenant import SYSTEM_TENANT_ID
from src.backend.core.security.capabilities.vocabulary import (
    CapabilityVocabulary,
    build_default_vocabulary,
)

if TYPE_CHECKING:
    from src.backend.core.security.capabilities.policy import CapabilityPolicy

AuditCallback = Callable[[dict[str, object]], None]
"""Подпись audit-callback'а: принимает event dict, ничего не возвращает."""

_DEFAULT_LRU_SIZE: Final[int] = 1024

class AuditMixin:
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

        Поля ``tenant``, ``reason``, ``event`` — опциональные
        (передаются только в tenant-aware путях или для указания
        причины ``"policy"``). Старые callers (без этих kwargs) получают
        тот же event-dict, что и раньше — backward compat preserved.
        """
        if self._audit is None:
            return
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

