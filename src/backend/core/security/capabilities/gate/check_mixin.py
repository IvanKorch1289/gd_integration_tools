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

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Final

from src.backend.core.security.capabilities.errors import CapabilityDeniedError
from src.backend.core.security.capabilities.gate._protocol import (
    _CapabilityGateProtocol,
)
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

        Notes:
            D-AUDIT-98 fix (S183 W1.1): the initial ``cache_key in self._cache``
            read must be guarded by ``self._lock`` so that a concurrent
            ``_invalidate_plugin`` (which iterates ``cache.items()`` to
            rebuild the dict) cannot raise ``RuntimeError: dictionary
            changed size during iteration``. The remaining mutation goes
            through ``_cache_granted`` which already holds the lock.
        """
        cache_key = (plugin, capability, requested_scope)
        with self._lock:  # D-AUDIT-98 fix (S183 W1.1)
            cache_hit = cache_key in self._cache
        if cache_hit:
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
        self, capability: str, tenant: str, principal: str, scope: str | None = None,
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

            D-AUDIT-98 fix (S183 W1.1): cache reads/writes are guarded by
            ``self._lock``. ``cached_value`` is snapshotted under the lock,
            then the audit emit runs lock-free. Writes either go through
            ``_tenant_cache_granted`` (already locked) or are wrapped
            explicitly to prevent concurrent ``_invalidate_tenant`` from
            racing with the assignment.
        """
        cache_key = (tenant, principal, capability, scope)
        with self._lock:  # D-AUDIT-98 fix (S183 W1.1)
            if cache_key in self._tenant_cache:
                cached_value = self._tenant_cache[cache_key]
            else:
                cached_value = None
        if cached_value is not None:
            self._emit_audit(
                plugin=principal,
                capability=capability,
                requested_scope=scope,
                declared_scope=None,
                outcome="granted" if cached_value else "denied",
                tenant=tenant,
            )
            return cached_value

        # 1. Policy consultation.
        if self._policy is not None:
            decision = self._policy.evaluate(
                tenant=tenant, principal=principal, capability=capability, scope=scope,
            )
            if decision.effect == "deny":
                with self._lock:  # D-AUDIT-98 fix (S183 W1.1)
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
                with self._lock:  # D-AUDIT-98 fix (S183 W1.1)
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
            with self._lock:  # D-AUDIT-98 fix (S183 W1.1)
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
            with self._lock:  # D-AUDIT-98 fix (S183 W1.1)
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
            with self._lock:  # D-AUDIT-98 fix (S183 W1.1)
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
