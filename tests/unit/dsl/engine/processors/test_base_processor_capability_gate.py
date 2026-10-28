"""Unit-тесты capability-гейта DSL-процессоров (ADR-0366).

``BaseProcessor.auth_check`` — единая точка runtime-enforcement'а
``required_capability``. После ADR-0366 путь проверки:

* feature-flag ``dsl_capability_gate_enabled`` выключен → legacy-путь
  (``check_source_capability``), поведение не меняется;
* флаг включён → runtime-резолвер (``core.security.capabilities``):
  namespace = ``route_id`` роута → ``"core"`` (baseline) → fail-closed DENY.

Проверяется:

* deny для необъявленной capability;
* allow для capability, объявленной роутом;
* core-baseline требует явного флага;
* tenant-aware запрос без tenant → deny;
* principal берётся из ``exchange.meta`` и не используется как namespace.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from src.backend.core.config.features import feature_flags
from src.backend.core.security.capabilities.gate import (
    CapabilityGate,
    get_capability_gate,
)
from src.backend.core.security.capabilities.models import CapabilityRef
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

pytestmark = pytest.mark.unit


class _GateProcessor(BaseProcessor):
    """Процессор с одной декларированной capability."""

    required_capability = "rpa.file.list"

    async def process(self, exchange: Exchange[Any], context: Any) -> None:
        """Метод process (см. signature)."""


@pytest.fixture
def gate() -> Iterator[CapabilityGate]:
    """Изолированный process-wide singleton capability-гейта."""
    get_capability_gate.cache_clear()
    instance = get_capability_gate()
    yield instance
    get_capability_gate.cache_clear()


@pytest.fixture
def gate_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Runtime-enforcement capability-гейта включён."""
    monkeypatch.setattr(feature_flags, "dsl_capability_gate_enabled", True)


@pytest.fixture
def gate_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Runtime-enforcement capability-гейта выключен (legacy-путь)."""
    monkeypatch.setattr(feature_flags, "dsl_capability_gate_enabled", False)


@pytest.fixture
def baseline_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """Core-baseline выключен (default)."""
    monkeypatch.setattr(feature_flags, "dsl_capability_core_baseline_enabled", False)


@pytest.fixture
def baseline_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """Core-baseline явно включён."""
    monkeypatch.setattr(feature_flags, "dsl_capability_core_baseline_enabled", True)


def _exchange(*, route_id: str | None = None, tenant_id: str | None = None) -> Exchange[Any]:
    exchange = Exchange()
    exchange.meta.route_id = route_id
    exchange.meta.tenant_id = tenant_id
    return exchange


# ── Runtime-резолвер (флаг включён) ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_auth_check_denies_undeclared_capability(
    gate: CapabilityGate, gate_enabled: None, baseline_off: None
) -> None:
    """Capability, не объявленная роутом → DENY (fail-closed)."""
    processor = _GateProcessor()
    exchange = _exchange(route_id="my_route", tenant_id="tenant-1")

    allowed = await processor.auth_check(exchange, action="read")

    assert allowed is False
    assert exchange.error is not None and "denied" in exchange.error
    assert exchange.stopped is True


@pytest.mark.asyncio
async def test_auth_check_allows_capability_declared_by_route(
    gate: CapabilityGate, gate_enabled: None, baseline_off: None
) -> None:
    """Capability, объявленная роутом → ALLOW."""
    gate.declare("my_route", [CapabilityRef(name="rpa.file.list", scope="**")])
    processor = _GateProcessor()
    exchange = _exchange(route_id="my_route", tenant_id="tenant-1")

    allowed = await processor.auth_check(exchange, action="read")

    assert allowed is True
    assert exchange.error is None
    assert exchange.stopped is False


@pytest.mark.asyncio
async def test_auth_check_core_baseline_requires_flag(
    gate: CapabilityGate, gate_enabled: None, baseline_off: None
) -> None:
    """Без baseline-флага core-пространство недоступно."""
    processor = _GateProcessor()
    exchange = _exchange(route_id="my_route", tenant_id="tenant-1")

    assert await processor.auth_check(exchange, action="read") is False


@pytest.mark.asyncio
async def test_auth_check_core_baseline_allowed_with_flag(
    gate: CapabilityGate, gate_enabled: None, baseline_on: None
) -> None:
    """С baseline-флагом capability ядра доступна и без декларации роута."""
    processor = _GateProcessor()
    exchange = _exchange(route_id="my_route", tenant_id="tenant-1")

    assert await processor.auth_check(exchange, action="read") is True


@pytest.mark.asyncio
async def test_auth_check_denies_tenant_aware_request_without_tenant(
    gate: CapabilityGate, gate_enabled: None, baseline_off: None
) -> None:
    """Tenant-aware запрос без tenant → DENY (решение не атрибутировано)."""
    from src.backend.core.security.capabilities.runtime_resolver import (
        CapabilityRequest,
        check,
    )

    gate.declare("my_route", [CapabilityRef(name="rpa.file.list", scope="**")])

    decision = check(
        CapabilityRequest(capability="rpa.file.list", plugin="my_route"), gate=gate
    )

    assert decision.allowed is False
    assert decision.reason == "tenant_missing"


@pytest.mark.asyncio
async def test_auth_check_passes_tenant_and_principal_from_exchange_meta(
    gate: CapabilityGate, gate_enabled: None, baseline_off: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tenant и principal пробрасываются из ``exchange.meta`` в резолвер."""
    from src.backend.core.security.capabilities import runtime_resolver

    captured: dict[str, Any] = {}

    def _capture(request: Any, *, principal: str | None = None, gate: Any = None) -> Any:
        captured["request"] = request
        captured["principal"] = principal
        return runtime_resolver.CapabilityDecision(
            allowed=True, plugin="my_route", reason="granted", capability=request.capability
        )

    monkeypatch.setattr(runtime_resolver, "check", _capture)

    processor = _GateProcessor()
    exchange = _exchange(route_id="my_route", tenant_id="tenant-42")
    exchange.meta.principal = "alice"

    allowed = await processor.auth_check(exchange, action="read")

    assert allowed is True
    assert captured["principal"] == "alice"
    assert captured["request"].tenant == "tenant-42"
    assert captured["request"].plugin == "my_route"


@pytest.mark.asyncio
async def test_auth_check_does_not_use_principal_as_namespace(
    gate: CapabilityGate, gate_enabled: None, baseline_off: None
) -> None:
    """Principal не используется как namespace (риск ADR-0361)."""
    processor = _GateProcessor()
    exchange = _exchange(route_id=None, tenant_id="tenant-1")
    exchange.meta.principal = "rpa.file.list"

    assert await processor.auth_check(exchange, action="read") is False


# ── Legacy-путь (флаг выключен) ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_auth_check_uses_legacy_gateway_when_flag_disabled(
    gate_disabled: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """При выключенном флаге работает legacy-путь ``check_source_capability``."""
    captured: dict[str, Any] = {}

    async def _allow(capability: str, **kwargs: Any) -> bool:
        captured["capability"] = capability
        captured.update(kwargs)
        return True

    monkeypatch.setattr(
        "src.backend.core.security.connector_auth.check_source_capability", _allow
    )

    processor = _GateProcessor()
    exchange = _exchange(route_id="my_route", tenant_id="tenant-42")
    exchange.meta.principal = "alice"

    allowed = await processor.auth_check(exchange, action="read")

    assert allowed is True
    assert captured["capability"] == "rpa.file.list"
    assert captured["principal"] == "alice"
    assert captured["extra_ctx"]["tenant_id"] == "tenant-42"
