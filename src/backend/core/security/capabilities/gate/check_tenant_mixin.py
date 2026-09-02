"""CheckTenantMixin — tenant-aware check (returns bool, не raise).

Sprint 54 (M2-#7 swarm audit): extracted из check_mixin.py для
single-responsibility split. check (raises) + check_tenant (bool return) —
две distinct responsibilities, теперь в отдельных mixin'ах.

Re-export из gate/__init__.py для backward-compat через CheckMixin
(сохраняет public API).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.backend.core.security.capabilities.gate._protocol import (
    _CapabilityGateProtocol,
)

if TYPE_CHECKING:
    pass


class CheckTenantMixin(_CapabilityGateProtocol):
    """Tenant-aware check: возвращает ``bool`` (не raise).

    Single responsibility: per-tenant + per-principal + per-capability
    policy+declaration evaluation. Не выбрасывает
    :class:`CapabilityDeniedError` — caller решает.

    D-AUDIT-98 fix (S183 W1.1): cache reads/writes are guarded by
    ``self._lock``. ``cached_value`` is snapshotted under the lock,
    then the audit emit runs lock-free. Writes either go through
    ``_tenant_cache_granted`` (already locked) or are wrapped
    explicitly to prevent concurrent ``_invalidate_tenant`` from
    racing with the assignment.

    Семантика: ``deny`` от policy → ``False`` *до* declaration-check.
    ``allow`` → ``True`` (skip declaration). ``no_match`` →
    fallback to per-tenant declaration.
    """

    __slots__ = ()

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
                tenant=tenant, principal=principal, capability=capability, scope=scope
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

        assert declared.scope is not None  # nosec
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
