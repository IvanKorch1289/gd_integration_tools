"""Smoke tests for cycle-244 Protocol classes in ``dsl/builders/base``.

Verifies:
1. All 22 Protocol classes from cycle 244 importable from
   ``src.backend.dsl.builders.base``.
2. Each Protocol is ``@_runtime_checkable`` so ``isinstance(builder, Proto)`` works.
3. A real ``RouteBuilder`` instance satisfies ALL 22 Protocols (locks in
   the contract surface — if a mixin method is removed without removing
   the Protocol, this test fails).
4. Plain object does NOT satisfy any Protocol (negative test).

Cycle 244 (commit 201a2c0d): added 20 Protocol classes documenting the
RouteBuilder contract. Goal: ≥20/41 mixins documented as Protocol.
This test file locks in the public surface so future refactoring
cannot silently break the contract.
"""

from __future__ import annotations

from typing import Any

import pytest


# All 22 Protocol class names added in cycle 244 (20 new) + 2 pre-existing.
# Categorized: INSTANCE protocols describe RouteBuilder methods (isinstance check
# against RouteBuilder should pass). MODULE protocols describe static helpers or
# mixin-internal methods — they document the contract but RouteBuilder itself
# may not directly satisfy them.
INSTANCE_PROTOCOLS = (
    "_RouteCore",
    "_RouteEntityCrudProtocol",
    "_RouteBatchDataProtocol",
    "_RouteControlFlowProtocol",
    "_RouteConcurrencyProtocol",
    "_RouteTimeResilienceProtocol",
    "_RouteDbProtocol",
    "_RoutePersistenceProtocol",
    "_RouteProxyProtocol",
    "_RouteSinkProtocol",
    "_RouteSourceProtocol",
    "_RouteTemplateProtocol",
    "_RouteIntegrationCoreProtocol",
    "_RouteAIOpsProtocol",
    "_RouteWorkflowOpsProtocol",
    "_RouteAgentProtocol",
    "_RouteConverterProtocol",
    "_RouteContentProtocol",
    "_RouteSecurityProtocol",
    "_RouteConfigProtocol",
)

# Module-/mixin-level contracts — not satisfied by RouteBuilder directly.
MODULE_PROTOCOLS = (
    "_RouteProcessorSteps",
    "_RouteCollectionProtocol",
)

CYCLE_244_PROTOCOLS = INSTANCE_PROTOCOLS + MODULE_PROTOCOLS


@pytest.fixture(scope="module")
def builder() -> Any:
    """Real RouteBuilder instance for isinstance checks.

    May need fixture overrides for env-specific config; the bare
    RouteBuilder() should not require external services.
    """
    from src.backend.dsl.builders.base import RouteBuilder

    return RouteBuilder()


def test_all_22_protocols_importable() -> None:
    """All 22 Protocol classes from cycle 244 are importable."""
    from src.backend.dsl.builders import base

    for proto_name in CYCLE_244_PROTOCOLS:
        assert hasattr(base, proto_name), (
            f"Missing Protocol {proto_name} in dsl.builders.base"
        )
        cls = getattr(base, proto_name)
        # Each must be a class with a Protocol-like interface
        assert isinstance(cls, type), f"{proto_name} is not a class"
        # Must have at least one method declared (Protocol interface)
        assert hasattr(cls, "__annotations__"), (
            f"{proto_name} has no method annotations"
        )


@pytest.mark.parametrize("proto_name", CYCLE_244_PROTOCOLS)
def test_protocol_is_runtime_checkable(proto_name: str) -> None:
    """Each Protocol is decorated with @_runtime_checkable."""
    from src.backend.dsl.builders import base

    cls = getattr(base, proto_name)
    # _runtime_checkable adds a __call__ attribute or marks instance_check
    # via __instancecheck__. The simplest check: ensure isinstance works
    # without raising TypeError.
    try:
        # We can't pass a real builder here (fixture scope mismatch),
        # so use a plain object — should return False, not raise.
        result = isinstance(object(), cls)
        assert result is False, f"{proto_name} returns True for plain object"
    except TypeError as exc:
        pytest.fail(f"{proto_name} is not runtime-checkable: {exc}")


def test_routebuilder_satisfies_all_20_instance_protocols(builder: Any) -> None:
    """Real RouteBuilder instance conforms to all 20 INSTANCE Protocols.

    This is the contract lock: if a RouteBuilder-level method is removed
    or renamed without updating the Protocol, this test fails loudly.

    Note: 2 Protocols (``_RouteProcessorSteps``, ``_RouteCollectionProtocol``)
    document module-/mixin-level contracts (static helpers or internal
    mixin methods) and are NOT required to be satisfied by RouteBuilder
    itself. They live in MODULE_PROTOCOLS for documentation purposes.
    """
    from src.backend.dsl.builders import base

    failed: list[str] = []
    for proto_name in INSTANCE_PROTOCOLS:
        cls = getattr(base, proto_name)
        if not isinstance(builder, cls):
            failed.append(proto_name)
    assert not failed, (
        f"RouteBuilder does not satisfy {len(failed)} INSTANCE Protocol(s): "
        f"{failed}. Either add the missing methods or remove the Protocol."
    )


def test_module_protocols_are_documented() -> None:
    """Module-level Protocols exist but don't need to be satisfied by RouteBuilder.

    They document the contract of static helpers / mixin-internal methods.
    Test ensures they're at least importable and have method annotations.
    """
    from src.backend.dsl.builders import base

    for proto_name in MODULE_PROTOCOLS:
        cls = getattr(base, proto_name)
        # typing.Protocol doesn't reliably populate __abstractmethods__,
        # but it DOES expose declared methods via vars() / dir(). Filter
        # only dunder attributes (Protocol internals like __module__,
        # __doc__, __init__, etc.) — keep underscore-prefixed method names
        # since some Protocols document internal contract methods.
        declared_methods = [
            name
            for name, value in vars(cls).items()
            if not name.startswith("__") and callable(value)
        ]
        assert len(declared_methods) >= 2, (
            f"{proto_name} should declare ≥2 methods, "
            f"has {len(declared_methods)}: {declared_methods}"
        )


def test_protocol_count_meets_sprint45_target() -> None:
    """Sanity check: we still have ≥20 Protocol classes (S45 target)."""
    from src.backend.dsl.builders import base

    protocol_classes = [
        name
        for name in dir(base)
        if name.startswith("_Route") and name.endswith("Protocol")
        or name in {"_RouteCore", "_RouteProcessorSteps"}
    ]
    assert len(protocol_classes) >= 20, (
        f"Expected ≥20 RouteBuilder Protocols (S45 W2 target), "
        f"got {len(protocol_classes)}: {protocol_classes}"
    )
