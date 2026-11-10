"""Unit-тесты runtime-резолвера capability-гейта (ADR-0366).

Резолвер переносит namespace-логику capability-контроля из DSL-слоя в
``core``: кандидат namespace — ``route_id`` (плагин роута), fallback —
``"core"`` (baseline), иначе fail-closed DENY.

Проверяется (ADR-0366):

* ``route_id`` с декларацией → ALLOW под namespace'ом роута;
* ``"core"`` — только при ``dsl_capability_core_baseline_enabled``;
* capability без декларации → DENY (fail-closed);
* запрос без tenant → DENY (решение нельзя отнести к тенанту);
* ``principal`` не является namespace'ом (в API резолвера его нет).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from src.backend.core.config.features import feature_flags
from src.backend.core.security.capabilities.gate import (
    CapabilityGate,
    get_capability_gate,
)
from src.backend.core.security.capabilities.models import CapabilityRef
from src.backend.core.security.capabilities.runtime_resolver import (
    CapabilityRequest,
    check,
    resolve_plugin,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def gate() -> Iterator[CapabilityGate]:
    """Изолированный process-wide singleton capability-гейта."""
    get_capability_gate.cache_clear()
    instance = get_capability_gate()
    yield instance
    get_capability_gate.cache_clear()


@pytest.fixture
def baseline_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """Core-baseline выключен (default)."""
    monkeypatch.setattr(feature_flags, "dsl_capability_core_baseline_enabled", False)


@pytest.fixture
def baseline_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """Core-baseline явно включён."""
    monkeypatch.setattr(feature_flags, "dsl_capability_core_baseline_enabled", True)


# ── resolve_plugin ─────────────────────────────────────────────────────────────


def test_resolve_plugin_prefers_route_declaration(
    gate: CapabilityGate, baseline_off: None
) -> None:
    """Декларация роута — приоритетный namespace."""
    gate.declare("my_route", [CapabilityRef(name="rpa.file.list", scope="**")])

    request = CapabilityRequest(
        capability="rpa.file.list", plugin="my_route", tenant="tenant-1"
    )

    assert resolve_plugin(request, gate=gate) == "my_route"


def test_resolve_plugin_denies_without_declaration(
    gate: CapabilityGate, baseline_off: None
) -> None:
    """Без декларации и без baseline → namespace не резолвится (fail-closed)."""
    request = CapabilityRequest(
        capability="rpa.file.list", plugin="my_route", tenant="tenant-1"
    )

    assert resolve_plugin(request, gate=gate) is None


def test_resolve_plugin_core_baseline_requires_flag(
    gate: CapabilityGate, baseline_off: None
) -> None:
    """Core-baseline закрыт без явного флага."""
    request = CapabilityRequest(
        capability="rpa.file.list", plugin="my_route", tenant="tenant-1"
    )

    assert resolve_plugin(request, gate=gate) is None


def test_resolve_plugin_core_baseline_enabled(
    gate: CapabilityGate, baseline_on: None
) -> None:
    """Core-baseline открывается флагом для capability из CORE_CAPABILITIES."""
    request = CapabilityRequest(
        capability="rpa.file.list", plugin="my_route", tenant="tenant-1"
    )

    assert resolve_plugin(request, gate=gate) == "core"


def test_resolve_plugin_ignores_capability_outside_core_baseline(
    gate: CapabilityGate, baseline_on: None
) -> None:
    """Baseline открывает только capability из CORE_CAPABILITIES."""
    request = CapabilityRequest(
        capability="audit.write", plugin="my_route", tenant="tenant-1"
    )

    assert resolve_plugin(request, gate=gate) is None


def test_resolve_plugin_never_uses_principal_as_namespace(
    gate: CapabilityGate, baseline_off: None
) -> None:
    """В API резолвера нет principal — namespace'ом может быть только plugin."""
    assert "principal" not in CapabilityRequest.__dataclass_fields__

    request = CapabilityRequest(capability="rpa.file.list", tenant="tenant-1")

    assert resolve_plugin(request, gate=gate) is None


# ── ADR-0416 (дефект 2): namespace "core" подчиняется флагу baseline ─────────


def test_resolve_plugin_core_namespace_requires_baseline_flag(
    gate: CapabilityGate, baseline_off: None
) -> None:
    """Декларация в namespace "core" не обходит флаг baseline (ADR-0416).

    Namespace ``core`` — это **сам** core-baseline: он открывается только
    явным флагом ``dsl_capability_core_baseline_enabled``. Раньше ветка
    ``has_declaration("core", ...)`` проверялась до флага, и baseline был
    открыт всегда (в prod, где флаг выключен, — blanket-доступ к
    capability ядра).
    """
    request = CapabilityRequest(
        capability="rpa.browser.launch", plugin="core", tenant="tenant-1"
    )

    assert resolve_plugin(request, gate=gate) is None


def test_resolve_plugin_core_namespace_allowed_with_baseline_flag(
    gate: CapabilityGate, baseline_on: None
) -> None:
    """С флагом baseline namespace "core" доступен для capability ядра."""
    request = CapabilityRequest(
        capability="rpa.browser.launch", plugin="core", tenant="tenant-1"
    )

    assert resolve_plugin(request, gate=gate) == "core"


# ── check ──────────────────────────────────────────────────────────────────────


def test_check_allows_declared_capability(
    gate: CapabilityGate, baseline_off: None
) -> None:
    """Capability, объявленная роутом → ALLOW."""
    gate.declare("my_route", [CapabilityRef(name="rpa.file.list", scope="**")])

    decision = check(
        CapabilityRequest(
            capability="rpa.file.list", plugin="my_route", tenant="tenant-1"
        ),
        gate=gate,
    )

    assert decision.allowed is True
    assert decision.plugin == "my_route"
    assert decision.reason == "granted"


def test_check_denies_undeclared_capability(
    gate: CapabilityGate, baseline_off: None
) -> None:
    """Capability без декларации → DENY (fail-closed)."""
    decision = check(
        CapabilityRequest(
            capability="rpa.file.list", plugin="my_route", tenant="tenant-1"
        ),
        gate=gate,
    )

    assert decision.allowed is False
    assert decision.plugin is None
    assert decision.reason == "no_declaration"


def test_check_denies_request_without_tenant(
    gate: CapabilityGate, baseline_off: None
) -> None:
    """Tenant-aware запрос без tenant → DENY (решение не атрибутировано)."""
    gate.declare("my_route", [CapabilityRef(name="rpa.file.list", scope="**")])

    decision = check(
        CapabilityRequest(capability="rpa.file.list", plugin="my_route"), gate=gate
    )

    assert decision.allowed is False
    assert decision.reason == "tenant_missing"


def test_check_denies_scope_mismatch(gate: CapabilityGate, baseline_off: None) -> None:
    """Запрошенный scope не покрывается декларацией → DENY."""
    gate.declare("my_route", [CapabilityRef(name="rpa.file.list", scope="/data/in")])

    decision = check(
        CapabilityRequest(
            capability="rpa.file.list",
            plugin="my_route",
            scope="/etc/passwd",
            tenant="tenant-1",
        ),
        gate=gate,
    )

    assert decision.allowed is False
    assert decision.reason == "capability_denied"


def test_check_uses_core_baseline_when_enabled(
    gate: CapabilityGate, baseline_on: None
) -> None:
    """С флагом baseline capability ядра доступна и без декларации роута."""
    decision = check(
        CapabilityRequest(
            capability="rpa.file.list", plugin="my_route", tenant="tenant-1"
        ),
        gate=gate,
    )

    assert decision.allowed is True
    assert decision.plugin == "core"


def test_check_denies_unknown_capability(
    gate: CapabilityGate, baseline_on: None
) -> None:
    """Capability вне vocabulary → DENY (no_declaration), а не исключение."""
    decision = check(
        CapabilityRequest(
            capability="rpa.not.exists", plugin="my_route", tenant="tenant-1"
        ),
        gate=gate,
    )

    assert decision.allowed is False
    assert decision.reason == "no_declaration"


def test_check_denies_stale_declaration_outside_vocabulary(
    gate: CapabilityGate, baseline_on: None
) -> None:
    """Декларация, вышедшая из vocabulary → DENY (fail-closed), не исключение.

    Сценарий: capability была объявлена в гейте, а затем удалена из
    vocabulary (смена набора capability). Проверка обязана fail-closed.
    """
    gate._declarations.setdefault("my_route", {})["audit.gone"] = CapabilityRef(
        name="audit.gone", scope="**"
    )

    decision = check(
        CapabilityRequest(
            capability="audit.gone", plugin="my_route", tenant="tenant-1"
        ),
        gate=gate,
    )

    assert decision.allowed is False
    assert decision.reason == "unknown_capability"


# ── ADR-0416 (дефект 2): check() по namespace "core" ────────────────────────


def test_check_denies_core_namespace_without_baseline_flag(
    gate: CapabilityGate, baseline_off: None
) -> None:
    """Без флага baseline запрос в namespace "core" → DENY (no_declaration)."""
    decision = check(
        CapabilityRequest(
            capability="rpa.browser.launch", plugin="core", tenant="tenant-1"
        ),
        gate=gate,
    )

    assert decision.allowed is False
    assert decision.reason == "no_declaration"


def test_check_grants_core_baseline_with_flag(
    gate: CapabilityGate, baseline_on: None
) -> None:
    """С флагом baseline core-baseline выдаёт capability ядра.

    Scope при этом **не** сверяется: baseline означает «ядро использует свою
    capability», а не доступ к ресурсу (ADR-0416). Ресурсные capability
    (``fs.*``, ``net.*``, ``storage.*``) в baseline не входят — их
    объявляет владелец ресурса.
    """
    decision = check(
        CapabilityRequest(
            capability="rpa.browser.launch", plugin="core", tenant="tenant-1"
        ),
        gate=gate,
    )

    assert decision.allowed is True
    assert decision.plugin == "core"
    assert decision.reason == "core_baseline"


def test_check_core_baseline_still_requires_tenant(
    gate: CapabilityGate, baseline_on: None
) -> None:
    """Core-baseline не отменяет tenant-атрибуцию (ADR-0366 §3)."""
    decision = check(
        CapabilityRequest(capability="rpa.browser.launch", plugin="core"), gate=gate
    )

    assert decision.allowed is False
    assert decision.reason == "tenant_missing"
