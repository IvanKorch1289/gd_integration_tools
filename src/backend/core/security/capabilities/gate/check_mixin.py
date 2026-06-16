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

from src.backend.core.security.capabilities.errors import CapabilityDeniedError
from src.backend.core.security.capabilities.tenant import SYSTEM_TENANT_ID

if TYPE_CHECKING:
    pass

AuditCallback = Callable[[dict[str, object]], None]
"""Подпись audit-callback'а: принимает event dict, ничего не возвращает."""

_DEFAULT_LRU_SIZE: Final[int] = 1024


class CheckMixin(_CapabilityGateProtocol):
    """main capability check (check, check_tenant — the BIG methods) для CapabilityGate. S54 W4 extraction."""

    __slots__ = ()

    def check(self, plugin: str, capability: str, requested_scope: str | None) -> None:
        """Проверить, разрешён ли вызов; raise при denied.

        Args:
            plugin: Имя плагина / route'а.
            capability: Имя capability (``db.read``, и т.д.).
            requested_scope: Scope, который реально нужен runtime.

        Raises:
            CapabilityDeniedError: Декларация отсутствует, scope
                не покрывается, или policy вернула ``deny``.
            CapabilityNotFoundError: Имя отсутствует в vocabulary.
        """
        cache_key = (plugin, capability, requested_scope)
        if cache_key in self._cache:
            self._emit_audit(
                plugin=plugin,
                capability=capability,
                requested_scope=requested_scope,
                declared_scope=None,
                outcome="granted",
            )
            return

        # Policy consultation (before declaration check).
        if self._policy is not None:
            decision = self._policy.evaluate(
                tenant=SYSTEM_TENANT_ID,
                principal=plugin,
                capability=capability,
                scope=requested_scope,
            )
            if decision.effect == "deny":
                self._emit_audit(
                    plugin=plugin,
                    capability=capability,
                    requested_scope=requested_scope,
                    declared_scope=None,
                    outcome="denied",
                    reason="policy",
                )
                raise CapabilityDeniedError(
                    plugin=plugin,
                    capability=capability,
                    requested_scope=requested_scope,
                    declared_scope=None,
                )
            if decision.effect == "allow":
                # Policy explicitly allows → skip declaration check.
                self._cache_granted(cache_key)
                self._emit_audit(
                    plugin=plugin,
                    capability=capability,
                    requested_scope=requested_scope,
                    declared_scope=None,
                    outcome="granted",
                    reason="policy",
                )
                return
            # no_match → fall through to declaration check.

        declared = self._declarations.get(plugin, {}).get(capability)
        if declared is None:
            self._emit_audit(
                plugin=plugin,
                capability=capability,
                requested_scope=requested_scope,
                declared_scope=None,
                outcome="denied",
            )
            raise CapabilityDeniedError(
                plugin=plugin,
                capability=capability,
                requested_scope=requested_scope,
                declared_scope=None,
            )

        definition = self._vocabulary.get(capability)

        # Capability с `scope_required=False` принимает любой scope.
        if not definition.scope_required:
            self._cache_granted(cache_key)
            self._emit_audit(
                plugin=plugin,
                capability=capability,
                requested_scope=requested_scope,
                declared_scope=declared.scope,
                outcome="granted",
            )
            return

        if requested_scope is None:
            self._emit_audit(
                plugin=plugin,
                capability=capability,
                requested_scope=requested_scope,
                declared_scope=declared.scope,
                outcome="denied",
            )
            raise CapabilityDeniedError(
                plugin=plugin,
                capability=capability,
                requested_scope=None,
                declared_scope=declared.scope,
            )

        # Mypy: declared.scope is not None потому что validate_ref
        # отвергает scope=None при scope_required=True.
        assert declared.scope is not None
        if not definition.matcher.match(requested_scope, declared.scope):
            self._emit_audit(
                plugin=plugin,
                capability=capability,
                requested_scope=requested_scope,
                declared_scope=declared.scope,
                outcome="denied",
            )
            raise CapabilityDeniedError(
                plugin=plugin,
                capability=capability,
                requested_scope=requested_scope,
                declared_scope=declared.scope,
            )

        self._cache_granted(cache_key)
        self._emit_audit(
            plugin=plugin,
            capability=capability,
            requested_scope=requested_scope,
            declared_scope=declared.scope,
            outcome="granted",
        )

    def check_tenant(
        self, capability: str, tenant: str, principal: str, scope: str | None = None
    ) -> bool:
        """Tenant-aware check: возвращает ``bool`` (не raise).

        Args:
            capability: Имя capability (``db.read``, ``net.outbound``).
            tenant: Tenant-id (``"tenant_a"`` или :data:`SYSTEM_TENANT_ID`).
            principal: Principal-id (плагин/route).
            scope: Запрошенный scope (или ``None``).

        Returns:
            ``True`` если granted, ``False`` если denied.

        Notes:
            Семантика: ``deny`` от policy → ``False`` *до* declaration-check.
            ``allow`` → ``True`` (skip declaration). ``no_match`` →
            fallback to per-tenant declaration. Не выбрасывает
            :class:`CapabilityDeniedError` — caller сам решает.
        """
        cache_key = (tenant, principal, capability, scope)
        if cache_key in self._tenant_cache:
            cached = self._tenant_cache[cache_key]
            self._emit_audit(
                plugin=principal,
                capability=capability,
                requested_scope=scope,
                declared_scope=None,
                outcome="granted" if cached else "denied",
                tenant=tenant,
            )
            return cached

        # 1. Policy consultation.
        if self._policy is not None:
            decision = self._policy.evaluate(
                tenant=tenant, principal=principal, capability=capability, scope=scope
            )
            if decision.effect == "deny":
                self._tenant_cache[cache_key] = False
                self._emit_audit(
                    plugin=principal,
                    capability=capability,
                    requested_scope=scope,
                    declared_scope=None,
                    outcome="denied",
                    tenant=tenant,
                    reason="policy",
                )
                return False
            if decision.effect == "allow":
                self._tenant_cache[cache_key] = True
                self._emit_audit(
                    plugin=principal,
                    capability=capability,
                    requested_scope=scope,
                    declared_scope=None,
                    outcome="granted",
                    tenant=tenant,
                    reason="policy",
                )
                return True
            # no_match → fall through.

        # 2. Per-tenant declaration check.
        declared = (
            self._tenant_declarations.get(tenant, {}).get(principal, {}).get(capability)
        )
        if declared is None:
            self._tenant_cache[cache_key] = False
            self._emit_audit(
                plugin=principal,
                capability=capability,
                requested_scope=scope,
                declared_scope=None,
                outcome="denied",
                tenant=tenant,
            )
            return False

        definition = self._vocabulary.get(capability)
        if not definition.scope_required:
            self._tenant_cache_granted(cache_key)
            self._emit_audit(
                plugin=principal,
                capability=capability,
                requested_scope=scope,
                declared_scope=declared.scope,
                outcome="granted",
                tenant=tenant,
            )
            return True

        if scope is None:
            self._tenant_cache[cache_key] = False
            self._emit_audit(
                plugin=principal,
                capability=capability,
                requested_scope=scope,
                declared_scope=declared.scope,
                outcome="denied",
                tenant=tenant,
            )
            return False

        assert declared.scope is not None
        if not definition.matcher.match(scope, declared.scope):
            self._tenant_cache[cache_key] = False
            self._emit_audit(
                plugin=principal,
                capability=capability,
                requested_scope=scope,
                declared_scope=declared.scope,
                outcome="denied",
                tenant=tenant,
            )
            return False

        self._tenant_cache_granted(cache_key)
        self._emit_audit(
            plugin=principal,
            capability=capability,
            requested_scope=scope,
            declared_scope=declared.scope,
            outcome="granted",
            tenant=tenant,
        )
        return True
