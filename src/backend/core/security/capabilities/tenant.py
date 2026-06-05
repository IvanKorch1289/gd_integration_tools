"""Sprint 36 (V15 GAP, Subagent A) — :class:`CapabilityTenant` + :class:`TenantContext`.

Назначение:
    Изоляция деклараций capabilities по tenant'ам. Плагин/route, задекларированный
    для ``tenant_a``, не виден для ``tenant_b``. Default tenant = ``"_system"``
    (backward compat с существующим ``CapabilityGate.check()``).

Использование::

    from src.backend.core.security.capabilities.tenant import (
        CapabilityTenant, TenantContext,
    )

    tenant = CapabilityTenant(id="tenant_a", principal="plugin_credit")
    ctx = TenantContext(tenant_id="tenant_a", principal_id="plugin_credit")
    if tenant.is_system:
        ...  # системный код без multi-tenant разделения

Backward compat:
    ``SYSTEM_TENANT_ID = "_system"`` — sentinel value для случаев, когда
    tenant context отсутствует. ``CapabilityGate.check()`` использует именно
    его, чтобы existing tests продолжали работать без изменений.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ("SYSTEM_TENANT_ID", "CapabilityTenant", "TenantContext")

SYSTEM_TENANT_ID: str = "_system"
"""Sentinel: код, выполняемый вне multi-tenant контекста."""


@dataclass(frozen=True, slots=True)
class CapabilityTenant:
    """Tenant, в рамках которого плагин/route декларирует capabilities.

    Attributes:
        id: Уникальный идентификатор tenant'а (``"tenant_a"``, ``"bank_a"``).
        principal: Имя principal'а (плагин/route), ассоциированного с tenant'ом.
            По умолчанию совпадает с ``id`` для удобства короткой записи.
        scope_glob: Опц. glob-фильтр, ограничивающий видимость capabilities
            внутри tenant'а (например, ``"db:tenant_a:*"``). ``None`` = без
            ограничений.

    Examples:
        >>> t = CapabilityTenant(id="tenant_a", principal="plugin_credit")
        >>> t.is_system
        False
        >>> sys = CapabilityTenant(id="_system", principal="core")
        >>> sys.is_system
        True
    """

    id: str
    principal: str
    scope_glob: str | None = None

    @property
    def is_system(self) -> bool:
        """``True`` если tenant — системный (sentinel :data:`SYSTEM_TENANT_ID`)."""
        return self.id == SYSTEM_TENANT_ID

    def __str__(self) -> str:
        """Строковое представление для logging (id + principal + scope_glob)."""
        suffix = f"@{self.scope_glob}" if self.scope_glob is not None else ""
        return f"Tenant({self.id}/{self.principal}{suffix})"


@dataclass(frozen=True, slots=True)
class TenantContext:
    """Контекст текущего запроса: связка tenant ↔ principal.

    Attributes:
        tenant_id: Идентификатор tenant'а (см. :class:`CapabilityTenant.id`).
        principal_id: Идентификатор principal'а (плагин/route/user).
        extra: Опц. словарь с дополнительным контекстом (request_id,
            correlation_id, route_id и т.п.) — для audit / structured logging.

    Examples:
        >>> ctx = TenantContext(tenant_id="t1", principal_id="plugin_a")
        >>> ctx.tenant_id
        't1'
    """

    tenant_id: str
    principal_id: str
    extra: dict[str, str] = field(default_factory=dict)

    def to_tenant(self) -> CapabilityTenant:
        """Материализовать :class:`CapabilityTenant` из контекста.

        ``scope_glob`` остаётся ``None`` — он задаётся явно на уровне gate'а
        (per-tenant policy), а не пробрасывается через context.
        """
        return CapabilityTenant(id=self.tenant_id, principal=self.principal_id)
