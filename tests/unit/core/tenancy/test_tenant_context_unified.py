"""Единый tenant-контекст: ``core.tenancy.TenantContext`` ↔ ``CapabilityTenant``.

Аудит волны 35, находка Z-07 (план улучшений P1-4/P1-5):

* ``core.tenancy.TenantContext`` **не умел** нести ``principal_id`` — отсюда
  workaround в фасаде: в tenant-ContextVar клался ``CapabilityTenant``
  (атрибут ``id``, но нет ``tenant_id``/``principal_id``);
* код ядра читал ``ctx.tenant_id``, capability-контур — ``ctx.principal_id``:
  одно из чтений всегда падало с ``AttributeError``, который глушился →
  проверка прав уходила в tenant-less режим (**fail-open**).

Закрыто здесь:

1. единый тип контекста (``TenantContext``) с ``tenant_id`` + ``principal_id``;
2. один объект в обоих контурах (ядро + capability) — инвариант
   ``CapabilityTenant.tenant_id == TenantContext.tenant_id``;
3. fail-closed установка: рассинхроненный контекст **не попадает** в
   ContextVar, поэтому проверка прав уходит в DENY, а не в tenant-less режим.
"""

from __future__ import annotations

import pytest

from src.backend.core.security.capabilities.gate import CapabilityGate
from src.backend.core.security.capabilities.models import CapabilityRef
from src.backend.core.security.capabilities.tenant import CapabilityTenant
from src.backend.core.tenancy import (
    TenantContext,
    TenantContextLike,
    current_tenant,
    get_principal_id,
    get_tenant_id,
    set_tenant,
    tenant_scope,
)
from src.backend.services.tenancy.facade import TenantFacade

pytestmark = pytest.mark.unit


class _DesyncedContext:
    """Контекст «до Z-07»: есть ``id``, но нет ``tenant_id``/``principal_id``."""

    def __init__(self, tenant_id: str, principal: str) -> None:
        self.id = tenant_id
        self.principal = principal


def _gate_with_declaration() -> CapabilityGate:
    """Гейт с декларацией ``db.read`` для пары (tenant_a, plugin_x)."""
    gate = CapabilityGate()
    gate.declare_tenant(
        CapabilityRef(name="db.read", scope="credit_db"),
        tenant="tenant_a",
        principal="plugin_x",
    )
    return gate


def _check_from_context(gate: CapabilityGate, capability: str, scope: str) -> bool:
    """Проверка прав по текущему tenant-контексту (как это делает контур).

    Отсутствие контекста или незаявленный principal → **DENY** (fail-closed).
    """
    ctx = current_tenant()
    if ctx is None:
        return False
    return gate.check_tenant(capability, ctx.tenant_id, ctx.principal_id or "", scope)


class TestUnifiedTenantContext:
    """Единый тип контекста несёт и tenant_id, и principal_id."""

    def test_tenant_context_carries_principal_id(self) -> None:
        """Канонический контекст умеет нести principal (Z-07)."""
        ctx = TenantContext(tenant_id="tenant_a", principal_id="plugin_x")

        assert ctx.tenant_id == "tenant_a"
        assert ctx.principal_id == "plugin_x"

    def test_capability_tenant_exposes_same_names(self) -> None:
        """``CapabilityTenant`` отдаёт те же имена полей, что и контекст ядра."""
        tenant = CapabilityTenant(id="tenant_a", principal="plugin_x")

        assert tenant.tenant_id == "tenant_a"
        assert tenant.principal_id == "plugin_x"
        assert isinstance(tenant, TenantContextLike)

    def test_both_types_satisfy_protocol(self) -> None:
        """Оба типа взаимозаменяемы по контракту tenant-контекста."""
        assert isinstance(TenantContext(tenant_id="t"), TenantContextLike)
        assert isinstance(CapabilityTenant(id="t", principal="p"), TenantContextLike)

    def test_invariant_tenant_ids_match(self) -> None:
        """Инвариант: CapabilityTenant.tenant_id == TenantContext.tenant_id."""
        ctx = TenantContext(tenant_id="tenant_a", principal_id="plugin_x")

        materialized = ctx.to_tenant()

        assert materialized.tenant_id == ctx.tenant_id
        assert materialized.principal_id == ctx.principal_id

    def test_invariant_round_trip(self) -> None:
        """Обратное преобразование сохраняет значения (единый тип)."""
        ctx = TenantContext(tenant_id="tenant_a", principal_id="plugin_x")

        restored = ctx.to_tenant().to_context()

        assert restored.tenant_id == ctx.tenant_id
        assert restored.principal_id == ctx.principal_id


class TestFacadeSetsSingleContext:
    """``with_tenant`` ставит один объект, видимый обоими контурами."""

    @pytest.mark.asyncio
    async def test_with_tenant_sets_canonical_context(self) -> None:
        """Фасад кладёт канонический ``TenantContext`` (не ``CapabilityTenant``)."""
        facade = TenantFacade()

        async with facade.with_tenant("tenant_a", principal_id="plugin_x") as ctx:
            assert isinstance(ctx, TenantContext)
            # Код ядра читает те же значения...
            assert current_tenant() is ctx
            assert get_tenant_id() == "tenant_a"
            assert get_principal_id() == "plugin_x"
            # ...и capability-контур видит те же значения.
            assert ctx.to_tenant().tenant_id == get_tenant_id()
            assert ctx.to_tenant().principal_id == get_principal_id()

    @pytest.mark.asyncio
    async def test_facade_principal_visible_to_capability_contour(self) -> None:
        """Principal из ``with_tenant`` доступен capability-контуру (было ``None``)."""
        facade = TenantFacade()
        gate = _gate_with_declaration()

        async with facade.with_tenant("tenant_a", principal_id="plugin_x"):
            assert facade.principal_id() == "plugin_x"
            assert _check_from_context(gate, "db.read", "credit_db") is True

    @pytest.mark.asyncio
    async def test_previous_context_restored(self) -> None:
        """После выхода из scope восстанавливается прежний контекст."""
        facade = TenantFacade()

        with tenant_scope(TenantContext(tenant_id="outer")):
            async with facade.with_tenant("inner", principal_id="plugin_x"):
                assert get_tenant_id() == "inner"
            assert get_tenant_id() == "outer"


class TestFailClosedOnDesync:
    """Рассинхрон контекста не может увести проверку прав в tenant-less режим."""

    def test_desynced_context_is_rejected(self) -> None:
        """Объект без ``tenant_id`` не устанавливается (TypeError, а не silent pass)."""
        with pytest.raises(TypeError):
            set_tenant(_DesyncedContext("tenant_a", "plugin_x"))  # type: ignore[arg-type]

    def test_desynced_context_is_rejected_by_bind(self) -> None:
        """Тот же запрет на пути ``bind_tenant`` (ASGI-middleware)."""
        from src.backend.core.tenancy import bind_tenant

        with pytest.raises(TypeError):
            bind_tenant(_DesyncedContext("tenant_a", "plugin_x"))  # type: ignore[arg-type]

    def test_capability_tenant_is_normalized_to_canonical(self) -> None:
        """``CapabilityTenant`` приводится к каноническому типу (значения те же)."""
        set_tenant(CapabilityTenant(id="tenant_a", principal="plugin_x"))  # type: ignore[arg-type]
        try:
            ctx = current_tenant()
            assert isinstance(ctx, TenantContext)
            assert ctx.tenant_id == "tenant_a"
            assert ctx.principal_id == "plugin_x"
        finally:
            set_tenant(None)

    @pytest.mark.asyncio
    async def test_rejected_desync_keeps_active_context(self) -> None:
        """После отказа контекст не подменяется — проверка прав остаётся привязанной к tenant'у."""
        facade = TenantFacade()
        gate = _gate_with_declaration()

        async with facade.with_tenant("tenant_a", principal_id="plugin_x") as ctx:
            with pytest.raises(TypeError):
                set_tenant(_DesyncedContext("tenant_b", "plugin_y"))  # type: ignore[arg-type]

            # Активный контекст не тронут...
            assert current_tenant() is ctx
            assert get_tenant_id() == "tenant_a"
            assert get_principal_id() == "plugin_x"
            # ...значит, права проверяются для своего tenant'а...
            assert _check_from_context(gate, "db.read", "credit_db") is True
            # ...а для чужого tenant'а — DENY (никакого tenant-less режима).
            assert (
                gate.check_tenant("db.read", "tenant_b", "plugin_x", "credit_db")
                is False
            )

    def test_empty_tenant_id_denies_permission_check(self) -> None:
        """Пустой tenant_id (fail-closed маркер) → проверка прав DENY."""
        gate = _gate_with_declaration()

        with tenant_scope(TenantContext(tenant_id="", principal_id="plugin_x")):
            assert _check_from_context(gate, "db.read", "credit_db") is False

    def test_no_context_denies_permission_check(self) -> None:
        """Вне tenant-scope проверка прав DENY (нет контекста — нет доступа)."""
        gate = _gate_with_declaration()

        assert _check_from_context(gate, "db.read", "credit_db") is False

    def test_to_tenant_does_not_substitute_system_principal(self) -> None:
        """Контекст без principal'а НЕ превращается в системного principal'а.

        Подмена ``principal_id=None → "_system"`` превращала бы «principal не
        заявлен» в «действует системный principal» → проверка прав, требующая
        principal'а, выдала бы доступ вместо отказа (fail-open).
        """
        ctx = TenantContext(tenant_id="tenant_a")

        tenant = ctx.to_tenant()

        assert tenant.principal_id is None
        assert tenant.principal is None
        assert tenant.tenant_id == "tenant_a"

    def test_to_tenant_keeps_declared_principal(self) -> None:
        """Объявленный principal'а сохраняется без искажений."""
        ctx = TenantContext(tenant_id="tenant_a", principal_id="plugin_x")

        tenant = ctx.to_tenant()

        assert tenant.principal_id == "plugin_x"
        assert tenant.tenant_id == "tenant_a"
