"""Protocol ``CapabilityGatewayProtocol`` (ADR-NEW-4, Sprint 17).

Назначение:
    Абстрагирует :class:`CapabilityGate` для единого фасада авторизации
    (:class:`AuthorizationGateway`, ADR-NEW-1). Позволяет:

    * подменять реальный gate на test-double без зависимости от
      ``capabilities/`` подмодуля;
    * композировать gate в цепочку с другими policy-движками
      (CapabilityPolicy → Casbin → OPA) в :class:`AuthorizationGateway`;
    * декларировать капабилити плагина/route'а в едином API.

Реализация:
    :class:`src.backend.core.security.capabilities.gate.CapabilityGate`
    реализует этот Protocol через ``@runtime_checkable``.

Sprint 36 (V15 GAP, Subagent A) additions:
    Tenant-scoped методы ``check_tenant`` / ``declare_tenant`` /
    ``revoke_tenant`` / ``list_allocated_tenant`` для multi-tenant
    изоляции. Backward compat preserved — original 3-method protocol
    остаётся subset нового.

Тестовый double:
    Любой объект с тремя базовыми методами (check / declare /
    list_allocated) автоматически удовлетворяет Protocol; для tenant-
    aware сценариев нужно реализовать 4 дополнительных метода.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, runtime_checkable

from src.backend.core.security.capabilities.models import CapabilityRef

__all__ = ("CapabilityGatewayProtocol",)


@runtime_checkable
class CapabilityGatewayProtocol(Protocol):
    """Унифицированный интерфейс capability-gate.

    Поведение каждого метода:

    * ``check(plugin, capability, scope)`` — проверяет, что плагин
      имеет декларацию capability с покрывающим scope; raise
      ``CapabilityDeniedError`` при denied.
    * ``declare(plugin, capabilities)`` — сохраняет декларацию плагина
      (обычно вызывается loader'ом до import ``entry_class``).
    * ``list_allocated(plugin)`` — возвращает имена capability,
      задекларированные для плагина (для audit и admin-UI).
    * ``check_tenant(capability, tenant, principal, scope)`` — то же,
      что ``check``, но возвращает ``bool`` (не raise) и работает в
      tenant-контексте.
    * ``declare_tenant(capability, tenant, principal)`` — декларация
      capability для пары (tenant, principal).
    * ``revoke_tenant(capability, tenant)`` — отзыв capability для
      tenant'а (через всех principal'ов).
    * ``list_allocated_tenant(tenant)`` — список деклараций для
      tenant'а (через всех principal'ов).

    Notes:
        Все scope-параметры — строки. Соответствие scope-pattern и
        реального scope проверяется через ``ScopeMatcher`` (см.
        :mod:`capabilities.scope`). Сам Protocol не определяет
        конкретный формат scope — это контракт реализации.
    """

    def check(self, plugin: str, capability: str, scope: str | None = None) -> None:
        """Проверить разрешение; raise при denied."""
        ...

    def declare(self, plugin: str, capabilities: Iterable[object]) -> None:
        """Задекларировать capabilities плагина/route'а."""
        ...

    def list_allocated(self, plugin: str) -> tuple[str, ...]:
        """Список имён задекларированных capabilities для плагина."""
        ...

    def check_tenant(
        self, capability: str, tenant: str, principal: str, scope: str | None = None
    ) -> bool:
        """Tenant-aware check; возвращает ``bool`` (не raise)."""
        ...

    def declare_tenant(
        self, capability: CapabilityRef, tenant: str, principal: str
    ) -> None:
        """Декларировать capability для пары (tenant, principal)."""
        ...

    def revoke_tenant(self, capability: str, tenant: str) -> None:
        """Отозвать capability для tenant'а (через всех principal'ов)."""
        ...

    def list_allocated_tenant(self, tenant: str) -> tuple[CapabilityRef, ...]:
        """Список деклараций capability для tenant'а."""
        ...
