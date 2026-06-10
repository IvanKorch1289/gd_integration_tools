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

class DeclarationMixin:
    """capability declaration/management (declare, revoke, tenant mgmt) для CapabilityGate. S54 W4 extraction."""

    __slots__ = ()

    def declare(self, plugin: str, capabilities: Iterable[CapabilityRef]) -> None:
        """Декларировать capabilities плагина/route'а.

        Вызывается :class:`PluginLoader` / :class:`RouteLoader` после
        парсинга манифеста и **до** ``import_module(entry_class)``.

        Raises:
            CapabilityNotFoundError: Имя capability отсутствует в
                vocabulary.
            ValueError: Уже задекларировано для этого плагина (по имени
                capability).
        """
        bucket = self._declarations.setdefault(plugin, {})
        for ref in capabilities:
            self._vocabulary.validate_ref(ref)
            if ref.name in bucket:
                raise ValueError(
                    f"Capability {ref.name!r} already declared for {plugin!r}"
                )
            bucket[ref.name] = ref
        # Любая новая декларация инвалидирует кэш для этого плагина.
        self._invalidate_plugin(plugin)

    def revoke(self, plugin: str) -> None:
        """Отозвать все декларации плагина (на shutdown / unload)."""
        self._declarations.pop(plugin, None)
        self._invalidate_plugin(plugin)

    def declare_tenant(
        self, capability: CapabilityRef, tenant: str, principal: str
    ) -> None:
        """Декларировать capability для пары (tenant, principal).

        Args:
            capability: Capability для декларации.
            tenant: Tenant-id.
            principal: Principal-id (плагин/route) внутри tenant'а.

        Raises:
            CapabilityNotFoundError: Имя capability отсутствует в
                vocabulary.
            ValueError: Уже задекларировано для этой пары
                (tenant, principal).
        """
        self._vocabulary.validate_ref(capability)
        tenant_bucket = self._tenant_declarations.setdefault(tenant, {})
        principal_bucket = tenant_bucket.setdefault(principal, {})
        if capability.name in principal_bucket:
            raise ValueError(
                f"Capability {capability.name!r} already declared for "
                f"tenant={tenant!r}, principal={principal!r}"
            )
        principal_bucket[capability.name] = capability
        # Invalidate per-tenant cache for this (tenant, principal).
        self._invalidate_tenant(tenant, principal)
        # Audit: capability.allocated.
        self._emit_audit(
            plugin=principal,
            capability=capability.name,
            requested_scope=capability.scope,
            declared_scope=capability.scope,
            outcome="granted",
            tenant=tenant,
            event="capability.allocated",
        )

    def revoke_tenant(self, capability: str, tenant: str) -> None:
        """Отозвать декларацию capability для tenant'а (для всех principal'ов).

        Args:
            capability: Имя capability для отзыва.
            tenant: Tenant-id.
        """
        revoked = False
        tenant_bucket = self._tenant_declarations.get(tenant)
        if tenant_bucket is not None:
            for principal, principal_bucket in list(tenant_bucket.items()):
                if capability in principal_bucket:
                    principal_bucket.pop(capability, None)
                    revoked = True
        # Invalidate per-tenant cache.
        self._invalidate_tenant(tenant)
        if revoked:
            self._emit_audit(
                plugin=SYSTEM_TENANT_ID,
                capability=capability,
                requested_scope=None,
                declared_scope=None,
                outcome="granted",
                tenant=tenant,
                event="capability.revoked",
            )

    def list_allocated_tenant(self, tenant: str) -> tuple[CapabilityRef, ...]:
        """Список capabilities, задекларированных для tenant'а.

        Возвращает **все** декларации для tenant'а (через всех
        principal'ов). Дедупликация не выполняется — caller'у видны
        все (principal, capability) пары.

        Args:
            tenant: Tenant-id.

        Returns:
            Кортеж :class:`CapabilityRef` (может быть пустым).
        """
        result: list[CapabilityRef] = []
        tenant_bucket = self._tenant_declarations.get(tenant)
        if tenant_bucket is not None:
            for principal_bucket in tenant_bucket.values():
                result.extend(principal_bucket.values())
        return tuple(result)

