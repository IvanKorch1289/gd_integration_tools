"""Regression tests для EIP ``@processor`` migration (B-04 fix, cycle 38).

Проверяет, что sample-файлы EIP processors (sample 5/41) зарегистрированы в
:func:`get_processor_registry` через ``@processor`` декоратор с валидными
spec_schema / output_schema / capabilities. Reference pattern для оставшихся
36 EIP процессоров (cycle 39).
"""

from __future__ import annotations

import pytest

# Top-level imports — триггерят module-level @processor регистрацию.
# Без них parametrized тесты запустятся ДО импорта модулей и увидят пустой registry.
from src.backend.dsl.engine.processors.eip.flow_control.throttler import (  # noqa: F401
    ThrottlerProcessor,
)
from src.backend.dsl.engine.processors.eip.reliability.redelivery_policy import (  # noqa: F401
    RedeliveryPolicyProcessor,
)
from src.backend.dsl.engine.processors.eip.resilience import (  # noqa: F401
    CircuitBreakerProcessor,
    DeadLetterProcessor,
    FallbackChainProcessor,
    TimeoutProcessor,
)
from src.backend.dsl.engine.processors.eip.routing_slip import (  # noqa: F401
    RoutingSlipProcessor,
)
from src.backend.dsl.registry.processor import ProcessorSpec, get_processor_registry

# ── Sample EIP processors (cycle 38 batch — 5 files, 7 classes total) ──


SAMPLE_EIP_FQNS: tuple[str, ...] = (
    "core:throttler",  # flow_control/throttler.py
    "core:redelivery_policy",  # reliability/redelivery_policy.py
    "core:routing_slip",  # routing_slip.py
    "core:dead_letter",  # resilience.py
    "core:fallback_chain",  # resilience.py
    "core:circuit_breaker",  # resilience.py
    "core:timeout",  # resilience.py
)


@pytest.mark.parametrize("fqn", SAMPLE_EIP_FQNS)
def test_eip_processor_registered(fqn: str) -> None:
    """Каждый sample EIP processor виден в реестре под ``core:<name>``."""
    registry = get_processor_registry()
    spec = registry.get(fqn)
    assert isinstance(spec, ProcessorSpec)
    assert spec.namespace == "core"
    assert spec.fqn == fqn


@pytest.mark.parametrize("fqn", SAMPLE_EIP_FQNS)
def test_eip_processor_has_io_schemas(fqn: str) -> None:
    """spec_schema и output_schema должны быть dict (не None)."""
    spec = get_processor_registry().get(fqn)
    assert isinstance(spec.spec_schema, dict)
    assert isinstance(spec.output_schema, dict)
    # spec_schema обязательно ``type: object`` для DSL-parametric processor
    assert spec.spec_schema.get("type") == "object"


@pytest.mark.parametrize("fqn", SAMPLE_EIP_FQNS)
def test_eip_processor_has_capability(fqn: str) -> None:
    """Каждый sample имеет хотя бы одну ``dsl.eip.*`` capability."""
    spec = get_processor_registry().get(fqn)
    assert spec.capabilities, f"{fqn} missing capabilities"
    assert any("dsl.eip" in cap for cap in spec.capabilities), (
        f"{fqn} has no dsl.eip.* capability: {spec.capabilities!r}"
    )


def test_eip_processor_classes_instantiable() -> None:
    """Decorated classes остаются BaseProcessor-инстанцируемыми."""
    from src.backend.dsl.engine.processors.base import BaseProcessor
    from src.backend.dsl.engine.processors.eip.routing_slip import SimpleRegistry

    # Resilience: 4 classes — required positional ``processors`` arg
    dlq = DeadLetterProcessor(processors=[])
    assert isinstance(dlq, BaseProcessor)

    fallback = FallbackChainProcessor(processors=[])
    assert isinstance(fallback, BaseProcessor)

    cb = CircuitBreakerProcessor(processors=[])
    assert isinstance(cb, BaseProcessor)

    timeout = TimeoutProcessor(processors=[])
    assert isinstance(timeout, BaseProcessor)

    # Routing slip: requires steps_resolver + registry
    slip = RoutingSlipProcessor(steps_resolver=lambda e: [], registry=SimpleRegistry())
    assert isinstance(slip, BaseProcessor)

    # Throttler: rate (positional)
    throttle = ThrottlerProcessor(rate=10.0)
    assert isinstance(throttle, BaseProcessor)

    # Redelivery: all-kwargs
    rd = RedeliveryPolicyProcessor()
    assert isinstance(rd, BaseProcessor)


def test_eip_registry_total_count_includes_samples() -> None:
    """Sample 5/41 + baseline processors ⇒ len >= 7 (наши samples)."""
    registry = get_processor_registry()
    specs = registry.list_specs()
    fqns = {s.fqn for s in specs}
    for fqn in SAMPLE_EIP_FQNS:
        assert fqn in fqns, f"{fqn} not in registry (got {sorted(fqns)[:10]}...)"


def test_eip_specs_have_eip_tag() -> None:
    """EIP процессоры должны иметь ``eip`` тег для категоризации."""
    for fqn in SAMPLE_EIP_FQNS:
        spec = get_processor_registry().get(fqn)
        assert "eip" in spec.tags, f"{fqn} missing 'eip' tag: {spec.tags!r}"


def test_resilience_replaces_not_used_in_sample() -> None:
    """Sample не использует replaces= — мы не override'им встроенные."""
    for fqn in SAMPLE_EIP_FQNS:
        spec = get_processor_registry().get(fqn)
        assert spec.replaces is None, (
            f"{fqn} should not replace another processor: {spec.replaces!r}"
        )
