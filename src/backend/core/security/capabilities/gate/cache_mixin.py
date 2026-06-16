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

from src.backend.core.security.capabilities.models import CapabilityRef

if TYPE_CHECKING:
    pass

AuditCallback = Callable[[dict[str, object]], None]
"""Подпись audit-callback'а: принимает event dict, ничего не возвращает."""

_DEFAULT_LRU_SIZE: Final[int] = 1024


class CacheMixin(_CapabilityGateProtocol):
    """cache + invalidation (granted caches, plugin/tenant invalidation) для CapabilityGate. S54 W4 extraction."""

    __slots__ = ()

    def declarations(self, plugin: str) -> tuple[CapabilityRef, ...]:
        """Возвращает текущий набор capabilities для плагина."""
        return tuple(self._declarations.get(plugin, {}).values())

    def list_allocated(self, plugin: str) -> tuple[str, ...]:
        """ADR-NEW-4 (S17): имена задекларированных capabilities плагина.

        Алиас для :meth:`declarations`, возвращающий только имена.
        Часть :class:`CapabilityGatewayProtocol` (``core.interfaces``).
        """
        return tuple(self._declarations.get(plugin, {}).keys())

    def _cache_granted(self, key: tuple[str, str, str | None]) -> None:
        """Положить granted-результат в LRU (с ограничением размера)."""
        if len(self._cache) >= self._lru_size:  # type: ignore[has-type]
            # Простейший LRU: выбрасываем самый старый ключ
            # (порядок dict'а сохраняет insertion order).
            oldest = next(iter(self._cache))  # type: ignore[has-type]
            self._cache.pop(oldest, None)  # type: ignore[has-type]
        self._cache[key] = True  # type: ignore[has-type]

    def _tenant_cache_granted(self, key: tuple[str, str, str, str | None]) -> None:
        """Положить granted-результат в per-tenant LRU."""
        if len(self._tenant_cache) >= self._lru_size:  # type: ignore[has-type]
            oldest = next(iter(self._tenant_cache))  # type: ignore[has-type]
            self._tenant_cache.pop(oldest, None)  # type: ignore[has-type]
        self._tenant_cache[key] = True  # type: ignore[has-type]

    def _invalidate_plugin(self, plugin: str) -> None:
        """Удалить из кэша все granted-записи для плагина."""
        self._cache = {key: v for key, v in self._cache.items() if key[0] != plugin}  # type: ignore[has-type]

    def _invalidate_tenant(self, tenant: str, principal: str | None = None) -> None:
        """Удалить из per-tenant кэша записи для (tenant, principal).

        Если ``principal=None`` — удаляются все записи для tenant'а.
        """
        if principal is None:
            self._tenant_cache = {  # type: ignore[has-type]
                key: v
                for key, v in self._tenant_cache.items()
                if key[0] != tenant  # type: ignore[has-type]
            }
        else:
            self._tenant_cache = {  # type: ignore[has-type]
                key: v
                for key, v in self._tenant_cache.items()  # type: ignore[has-type]
                if not (key[0] == tenant and key[1] == principal)
            }
