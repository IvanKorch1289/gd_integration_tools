"""Единый тип tenant-контекста (аудит волны 35: Z-07; план P1-4/P1-5).

Зачем
----
До волны 35 в проекте существовало **три** несовместимых tenant-контекста:

* ``core.tenancy.TenantContext`` — ``tenant_id`` / ``plan`` / ``region`` /
  ``rate_limit`` (ядро: ORM-фильтр, Redis-префикс, RLS, feature-flag traits);
* ``core.security.capabilities.tenant.TenantContext`` — ``tenant_id`` /
  ``principal_id`` / ``extra`` (capability-контур);
* ``core.security.capabilities.tenant.CapabilityTenant`` — ``id`` /
  ``principal`` / ``scope_glob`` (декларации capabilities).

``services.tenancy.TenantFacade.with_tenant()`` клал в tenant-ContextVar
третий тип (:class:`CapabilityTenant` — у него есть атрибут ``id``, но нет
``tenant_id``), тогда как код ядра читал ``ctx.tenant_id`` → ``AttributeError``,
который глушился → проверка прав уходила в tenant-less режим (**fail-open**,
аудит Z-07).

Здесь — единственный источник правды:

* :class:`TenantContext` — канонический контекст запроса; несёт и
  ``tenant_id``, и ``principal_id``;
* :class:`CapabilityTenant` — тот же tenant в терминах capability-декларации;
  алиасы ``tenant_id`` / ``principal_id`` делают его совместимым с
  :class:`TenantContext`;
* :class:`TenantContextLike` — протокол, которому удовлетворяют оба типа:
  и ``CapabilityTenant``, и любой объект с ``tenant_id``/``principal_id``;
* :func:`normalize_tenant_context` — fail-closed приведение к каноническому
  типу при установке: в ContextVar попадает **всегда** ``TenantContext``,
  поэтому рассинхрон (объект без ``tenant_id``) невозможен (аудит Z-07).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

__all__ = (
    "SYSTEM_TENANT_ID",
    "CapabilityTenant",
    "TenantContext",
    "TenantContextLike",
    "normalize_tenant_context",
)

SYSTEM_TENANT_ID: str = "_system"
"""Sentinel: код, выполняемый вне multi-tenant контекста."""


@runtime_checkable
class TenantContextLike(Protocol):
    """Минимальный контракт tenant-контекста.

    Удовлетворяют :class:`TenantContext`, :class:`CapabilityTenant` и любой
    объект с атрибутами ``tenant_id`` / ``principal_id``. Контракт используется
    для приведения к каноническому типу при установке в ContextVar
    (:func:`normalize_tenant_context`).

    Attributes:
        tenant_id: Идентификатор tenant'а.
        principal_id: Идентификатор principal'а (плагин/route/user).

    """

    @property
    def tenant_id(self) -> str:
        """Идентификатор tenant'а."""

    @property
    def principal_id(self) -> str | None:
        """Идентификатор principal'а (плагин/route/user)."""


@dataclass(frozen=True, slots=True)
class TenantContext:
    """Иммутабельный snapshot активного тенанта в пределах одного запроса.

    Attributes:
        tenant_id: Уникальный идентификатор организации (используется для
            изоляции данных, префикса Redis-ключей и routing).
        plan: Тарифный план (``free`` / ``basic`` / ``pro`` / ``enterprise``);
            определяет набор доступных функций и квот.
        region: Географический регион тенанта (для региональной маршрутизации
            и data-residency). По умолчанию ``ru``.
        rate_limit: Лимит запросов в минуту для тенанта; используется
            middleware и quota tracker'ом.
        principal_id: Идентификатор principal'а (плагин/route/user), который
            выполняет действие внутри tenant'а. ``None`` — principal не
            заявлен; проверки прав, требующие principal, обязаны отказать
            (fail-closed).
        extra: Дополнительный контекст (request_id, correlation_id, route_id)
            для audit / structured logging.

    Examples:
        >>> ctx = TenantContext(tenant_id="t1", principal_id="plugin_a")
        >>> ctx.tenant_id
        't1'
        >>> ctx.to_tenant().principal_id
        'plugin_a'

    """

    tenant_id: str
    plan: str = "free"  # free/basic/pro/enterprise
    region: str = "ru"
    rate_limit: int = 100  # req/min
    principal_id: str | None = None
    extra: dict[str, str] = field(default_factory=dict, hash=False)

    @property
    def is_system(self) -> bool:
        """``True`` если tenant — системный (sentinel :data:`SYSTEM_TENANT_ID`)."""
        return self.tenant_id == SYSTEM_TENANT_ID

    def to_tenant(self) -> CapabilityTenant:
        """Материализовать :class:`CapabilityTenant` из контекста.

        Инвариант единого типа: ``CapabilityTenant.tenant_id ==
        TenantContext.tenant_id`` и ``CapabilityTenant.principal_id ==
        TenantContext.principal_id`` — код ядра и capability-контур видят одни
        и те же значения.

        ``scope_glob`` остаётся ``None`` — он задаётся явно на уровне gate'а
        (per-tenant policy), а не пробрасывается через context.

        ``principal_id=None`` переносится **как None**, а не подменяется
        системным principal'ом: подмена превращала бы «principal не заявлен»
        в «действует системный principal» → проверка прав, требующая
        principal'а, выдала бы доступ вместо отказа (fail-open).
        """
        return CapabilityTenant(id=self.tenant_id, principal=self.principal_id)


@dataclass(frozen=True, slots=True)
class CapabilityTenant:
    """Tenant, в рамках которого плагин/route декларирует capabilities.

    Attributes:
        id: Уникальный идентификатор tenant'а (``"tenant_a"``, ``"bank_a"``).
        principal: Имя principal'а (плагин/route), ассоциированного с tenant'ом.
            ``None`` — principal не заявлен: проверки прав, требующие
            principal'а, обязаны отказать (fail-closed).
        scope_glob: Опц. glob-фильтр, ограничивающий видимость capabilities
            внутри tenant'а (например, ``"db:tenant_a:*"``). ``None`` = без
            ограничений.

    Examples:
        >>> t = CapabilityTenant(id="tenant_a", principal="plugin_credit")
        >>> t.is_system
        False
        >>> t.tenant_id
        'tenant_a'

    """

    id: str
    principal: str | None = None
    scope_glob: str | None = None

    @property
    def tenant_id(self) -> str:
        """Совместимое имя атрибута с :class:`TenantContext`.

        ``core.tenancy`` (ORM-фильтр, ``get_tenant_id()``, capability-гейт)
        читает ``ctx.tenant_id``, capability-контур — ``ctx.principal_id``.
        Алиасы дают те же значения, что и у канонического контекста, поэтому
        приведение к нему (:func:`normalize_tenant_context`) ничего не
        теряет.
        """
        return self.id

    @property
    def principal_id(self) -> str | None:
        """Совместимое имя атрибута с :class:`TenantContext.principal_id`."""
        return self.principal

    @property
    def is_system(self) -> bool:
        """``True`` если tenant — системный (sentinel :data:`SYSTEM_TENANT_ID`)."""
        return self.id == SYSTEM_TENANT_ID

    def to_context(self) -> TenantContext:
        """Материализовать канонический :class:`TenantContext` из типа.

        Обратная операция к :meth:`TenantContext.to_tenant` — оба конверта
        сохраняют одни и те же значения, поэтому
        ``CapabilityTenant.tenant_id == TenantContext.tenant_id`` и
        ``CapabilityTenant.principal_id == TenantContext.principal_id``.
        """
        return TenantContext(tenant_id=self.id, principal_id=self.principal)

    def __str__(self) -> str:
        """Строковое представление для logging (id + principal + scope_glob)."""
        suffix = f"@{self.scope_glob}" if self.scope_glob is not None else ""
        return f"Tenant({self.id}/{self.principal}{suffix})"


def normalize_tenant_context(ctx: object) -> TenantContext:
    """Fail-closed приведение объекта к каноническому tenant-контексту.

    Единая точка установки: в tenant-ContextVar попадает **всегда**
    :class:`TenantContext`, поэтому потребители (код ядра и capability-контур)
    читают одни и те же ``tenant_id`` / ``principal_id``, а рассинхрон
    (объект без ``tenant_id``) невозможен в принципе.

    Args:
        ctx: Кандидат на роль tenant-контекста.

    Returns:
        Канонический :class:`TenantContext`. Если ``ctx`` уже канонический —
        тот же объект; если это :class:`CapabilityTenant` (или иной объект с
        ``tenant_id`` / ``principal_id``) — новый контекст с теми же
        значениями.

    Raises:
        TypeError: объект не предоставляет ``tenant_id: str`` (или
            ``principal_id`` не является строкой). Такой контекст не должен
            попадать в ContextVar: потребители, читающие ``ctx.tenant_id``,
            упали бы с ``AttributeError`` — а именно это приводило к
            fail-open в проверке прав (аудит Z-07).

    """
    if isinstance(ctx, TenantContext):
        return ctx
    if not isinstance(ctx, TenantContextLike):
        raise TypeError(
            "tenant-контекст должен предоставлять 'tenant_id' и 'principal_id'; "
            f"получено {type(ctx).__name__}"
        )
    if not isinstance(ctx.tenant_id, str):
        raise TypeError(
            f"tenant_id должен быть str; получено {type(ctx.tenant_id).__name__}"
        )
    principal_id = ctx.principal_id
    if principal_id is not None and not isinstance(principal_id, str):
        raise TypeError(
            "principal_id должен быть str или None; получено "
            f"{type(principal_id).__name__}"
        )
    return TenantContext(tenant_id=ctx.tenant_id, principal_id=principal_id)
