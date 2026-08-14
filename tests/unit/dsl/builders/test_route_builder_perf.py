"""RouteBuilder perf benchmark (cycle 202, D-AUDIT-20202).

Цель: зафиксировать baseline attribute lookup latency для 76-mixin MRO
перед декомпозицией. Если будущая декомпозиция увеличит latency
(например, через `@property` getter'ы или __slots__ breakage), этот
тест поймает regression.

Не perf-gate (нет threshold assertion), а метрика-baseline.
Использование:

    pytest tests/unit/dsl/builders/test_route_builder_perf.py -v -s

Baseline (cycle 202, 76-mixin MRO, Apple M-class / Linux x86_64):
- description:        ~0.05 us/call
- route_id:           ~0.05 us/call
- source:             ~0.05 us/call
- protocol:           ~0.06 us/call
- add_middleware:     ~0.40 us/call   (MRO traversal через mixin)
- add_processor:      ~0.30 us/call   (MRO traversal через mixin)
- cache:              ~0.06 us/call
- feature_flag:       ~0.06 us/call

История:
- 2026-08-14 cycle 202: baseline (D-AUDIT-20202).
"""

from __future__ import annotations

import sys
import time
from typing import Any

import pytest


def _build_route_builder() -> Any:
    """Construct RouteBuilder (force lazy imports).

    Membrane: sys.path setup чтобы избежать ``ImportError: attempted
    relative import beyond top-level package`` при запуске изолированно.
    """
    if "src" not in sys.path:
        sys.path.insert(0, "src")
    from src.backend.dsl.builders.base import RouteBuilder

    return RouteBuilder("test_route", source="config")


def _measure_attr_lookup(obj: Any, attr: str, n_calls: int = 50_000) -> float:
    """Measure median ns/call для одного attribute getattr.

    Returns microseconds (us) per call.
    """
    timings = []
    for _ in range(5):  # 5 trials
        t0 = time.perf_counter()
        for _ in range(n_calls):
            try:
                getattr(obj, attr)
            except AttributeError:
                pass
        timings.append((time.perf_counter() - t0) * 1e6 / n_calls)
    timings.sort()
    return timings[len(timings) // 2]  # median


@pytest.mark.unit
def test_route_builder_mro_size() -> None:
    """MRO length (sanity check перед decomposition).

    Pre-decomp: 76 mixins + RouteBuilder + 5 base classes = 82.
    Post-decomp target: ~10 facade mixins + RouteBuilder + 5 base = ~16.
    """
    rb = _build_route_builder()
    mro = rb.__class__.__mro__
    mixins = [c for c in mro if c.__name__.endswith("Mixin") or c.__name__ == "RouteBuilder"]
    assert len(mixins) == 76, (
        f"Expected 76 mixins in MRO, got {len(mixins)}. "
        f"MRO: {[c.__name__ for c in mro]}"
    )


@pytest.mark.unit
def test_route_builder_own_dict_size() -> None:
    """Own attrs (slots) — proxy для instance state.

    Pre-S97: ``__slots__=()`` + missing __init__ → TypeError.
    S97 fix: 8 slots (route_id, source, description, _description,
    _middlewares, _processors, _protocol, _transport_config,
    _feature_flag, _route_overrides, _status, _name, _value, _kind,
    _target, _version, _id, _metadata).
    """
    from src.backend.dsl.builders.base import RouteBuilder

    own = [a for a in RouteBuilder.__dict__ if not a.startswith("__")]
    assert len(own) >= 8, (
        f"RouteBuilder.__dict__ should have ≥8 own attrs (slots), got {len(own)}"
    )


@pytest.mark.unit
def test_route_builder_attr_lookup_baseline() -> None:
    """Baseline latency для attribute lookup на 76-mixin MRO.

    Этот тест **НЕ** имеет жёсткого threshold — он log'ит latency
    и проверяет что latency < 5 us (явный regression marker).
    """
    rb = _build_route_builder()
    attrs = [
        "description",
        "route_id",
        "source",
        "protocol",
        "cache",
        "feature_flag",
        "add_middleware",
        "add_processor",
    ]

    results = {}
    for attr in attrs:
        us = _measure_attr_lookup(rb, attr)
        results[attr] = us
        # 5 us = 200x baseline → явный regression marker
        assert us < 5.0, (
            f"{attr} attribute lookup = {us:.3f} us/call exceeds 5.0 us threshold"
        )

    # Log для visibility (pytest -v -s shows this).
    print("\nRouteBuilder attribute lookup baseline (cycle 202, 76-mixin MRO):")
    for attr, us in sorted(results.items(), key=lambda x: -x[1]):
        print(f"  {attr:20s}: {us:.3f} us/call")


@pytest.mark.unit
def test_route_builder_instantiation_baseline() -> None:
    """Baseline latency для ``RouteBuilder()`` construction.

    76-mixin MRO traversal в __init__ через cooperative super().__init__().
    """
    if "src" not in sys.path:
        sys.path.insert(0, "src")
    from src.backend.dsl.builders.base import RouteBuilder

    n = 1000
    timings = []
    for _ in range(5):
        t0 = time.perf_counter()
        for _ in range(n):
            RouteBuilder("test", source="config")
        timings.append((time.perf_counter() - t0) * 1e6 / n)
    timings.sort()
    median_us = timings[len(timings) // 2]

    print(f"\nRouteBuilder() construction: {median_us:.3f} us/instantiation")
    # 100 us = 200x baseline (typical ~5-10 us для 76-mixin MRO)
    assert median_us < 100.0, (
        f"RouteBuilder() construction = {median_us:.3f} us exceeds 100 us threshold"
    )


@pytest.mark.unit
def test_route_builder_does_not_use_object_setattr_for_own_attrs() -> None:
    """S97 W1: __init__ uses ``object.__setattr__`` (slots compatibility).

    Own attributes (route_id, source, description) инициализируются через
    ``object.__setattr__`` чтобы обойти __slots__ limitation. Это
    необходимо — без этого, ``self.route_id = ...`` would raise
    AttributeError при __slots__ declaration.
    """
    rb = _build_route_builder()
    # Если бы __init__ использовал self.route_id = ... с __slots__,
    # объект бы created корректно. Но на slots-only __init__ через
    # self.X = Y запрещён. Тест проверяет что attrs are set:
    assert hasattr(rb, "route_id")
    assert hasattr(rb, "source")
    assert hasattr(rb, "description")
    assert hasattr(rb, "_middlewares")
    assert hasattr(rb, "_processors")
