"""Sprint 5 pilot batch — YAML round-trip тесты для 4 новых builder-методов.

Покрывает: ``webhook_verify``, ``jsonpath``, ``convert_units``, ``parse_ics``.
"""

# ruff: noqa: S101, S106

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


@pytest.mark.xfail(
    reason="S5 pilot processors (webhook_verify/jsonpath/convert_units/parse_ics) "
    "not fully implemented — to_spec() missing, round-trip blocked; S30 carryover"
)
@pytest.mark.parametrize(
    "method,kwargs",
    [
        ("webhook_verify", {"secret": "K"}),
        ("webhook_verify", {"secret": "K", "header": "X-Sig", "algorithm": "sha512"}),
        (
            "webhook_verify",
            {"secret": "K", "prefix": "v1", "on_mismatch": "warn"},
        ),
        ("jsonpath", {"expression": "$.user.email"}),
        ("jsonpath", {"expression": "$.x", "single": True, "to_property": "x"}),
        (
            "jsonpath",
            {
                "expression": "$.status",
                "mode": "update",
                "value": "approved",
            },
        ),
        (
            "jsonpath",
            {
                "expression": "$.b",
                "mode": "exists",
                "stop_on_missing": True,
            },
        ),
        ("convert_units", {"to_unit": "mile", "from_unit": "km"}),
        (
            "convert_units",
            {
                "to_unit": "fahrenheit",
                "precision": 2,
                "to_property": "temp_f",
            },
        ),
        ("parse_ics", {}),
        ("parse_ics", {"mode": "build", "prodid": "-//demo//RU"}),
        ("parse_ics", {"only_first": True}),
    ],
)
def test_pilot_batch_s5_round_trip(method: str, kwargs: dict) -> None:
    """Builder → YAML → builder идентичен для 4 новых процессоров."""
    builder = RouteBuilder.from_(f"rt.s5.{method}", source="test:rt.s5")
    getattr(builder, method)(**kwargs)
    original, rebuilt = _round_trip(builder)
    assert original == rebuilt, (
        f"Round-trip mismatch for {method}({kwargs}): {original} != {rebuilt}"
    )


@pytest.mark.xfail(
    reason="S5 pilot processors (webhook_verify/jsonpath/convert_units/parse_ics) "
    "not fully implemented — to_spec() missing, round-trip blocked; S30 carryover"
)
def test_pilot_batch_s5_full_chain() -> None:
    """Полный pipeline: webhook_verify → jsonpath → convert_units → parse_ics."""
    builder = (
        RouteBuilder.from_(
            "rt.s5.full", source="test:rt.s5.full", description="pilot batch"
        )
        .webhook_verify(secret="K", header="X-Hub-Signature-256", prefix="sha256")
        .jsonpath("$.payload.distance_km", single=True, to_property="distance_km")
        .convert_units(from_unit="km", to_unit="mile", precision=2)
        .parse_ics(only_first=True)
    )
    original, rebuilt = _round_trip(builder)
    assert original == rebuilt
    methods = [next(iter(p)) for p in original["processors"]]
    assert methods == ["webhook_verify", "jsonpath", "convert_units", "parse_ics"]
