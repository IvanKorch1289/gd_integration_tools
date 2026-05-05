"""W25.2 — Round-trip тесты builder → to_spec → load_pipeline_from_dict.

Проверяет, что для процессоров с примитивными аргументами цикл
``RouteBuilder → Pipeline.to_dict → load_pipeline_from_dict`` сохраняет
эквивалентность представления (по итоговому ``to_dict``).

Покрывает W25.2 supported subset: set_header / set_property / log /
transform / dispatch_action / enrich / throttle / delay.
"""

# ruff: noqa: S101

from __future__ import annotations

import pytest
import yaml

from src.backend.dsl.builder import RouteBuilder
from src.backend.dsl.yaml_loader import load_pipeline_from_yaml


def _round_trip(builder: RouteBuilder) -> tuple[dict, dict]:
    pipeline = builder.build()
    dump = pipeline.to_dict()
    yaml_str = yaml.safe_dump(dump, sort_keys=False, allow_unicode=True)
    rebuilt = load_pipeline_from_yaml(yaml_str)
    return dump, rebuilt.to_dict()


@pytest.mark.parametrize(
    "method,kwargs",
    [
        ("set_header", {"key": "x-trace", "value": "abc-123"}),
        ("set_property", {"key": "domain", "value": "orders"}),
        ("log", {"level": "warning"}),
        ("transform", {"expression": "items[?active].id"}),
        ("dispatch_action", {"action": "orders.create"}),
        ("enrich", {"action": "users.lookup"}),
        ("throttle", {"rate": 10.0}),
        ("delay", {"delay_ms": 250}),
    ],
)
def test_single_processor_round_trip(method: str, kwargs: dict) -> None:
    builder = RouteBuilder.from_("rt.single", source="test:rt.single")
    getattr(builder, method)(**kwargs)
    original, rebuilt = _round_trip(builder)
    assert original == rebuilt, f"Round-trip mismatch for {method}: {original} != {rebuilt}"


def test_multi_processor_pipeline_round_trip() -> None:
    builder = (
        RouteBuilder.from_("rt.multi", source="test:rt.multi", description="multi")
        .set_header(key="x-route-id", value="rt.multi")
        .set_property(key="domain", value="rt")
        .log(level="info")
        .transform(expression="data")
        .dispatch_action("rt.handler")
    )
    original, rebuilt = _round_trip(builder)
    assert original == rebuilt
    assert original["route_id"] == "rt.multi"
    assert len(original["processors"]) == 5


def test_dispatch_action_with_payload_factory_skipped_in_spec() -> None:
    """Процессор с callable-аргументом не сериализуется (to_spec → None)."""
    builder = (
        RouteBuilder.from_("rt.skip", source="test:rt.skip")
        .set_header(key="k", value="v")
        .dispatch_action("rt.handler", payload_factory=lambda ex: {"x": 1})
        .log(level="info")
    )
    pipeline = builder.build()
    spec = pipeline.to_dict()
    procs = spec["processors"]
    # dispatch_action с payload_factory выпал из spec'а; остальные сохранились.
    methods = [next(iter(p)) for p in procs]
    assert methods == ["set_header", "log"]
