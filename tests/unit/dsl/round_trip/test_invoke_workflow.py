# ruff: noqa: S101
"""Sprint 4 К3-B §6 — Round-trip тесты ``.invoke_workflow()``."""

from __future__ import annotations

from typing import Any

import pytest
import yaml

from src.backend.dsl.builder import RouteBuilder
from src.backend.dsl.yaml_loader import load_pipeline_from_yaml


def _round_trip(builder: RouteBuilder) -> tuple[dict, dict]:
    pipeline = builder.build(validate_actions=False)
    dump = pipeline.to_dict()
    yaml_str = yaml.safe_dump(dump, sort_keys=False, allow_unicode=True)
    rebuilt = load_pipeline_from_yaml(yaml_str)
    return dump, rebuilt.to_dict()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"name": "orders.create_with_payment"},
        {"name": "payments.charge_card", "mode": "sync"},
        {
            "name": "orders.create_with_payment",
            "mode": "async-api",
            "namespace": "tenant_a",
            "task_queue": "orders-queue",
        },
        {
            "name": "payments.charge_card",
            "mode": "sync",
            "result_property": "charge_result",
            "invocation_id_property": "wf_id",
        },
        # Sprint 8A K3 W11 — async-reply mode + custom timeout.
        {
            "name": "orders.long_running",
            "mode": "async-reply",
            "reply_timeout_seconds": 45.0,
        },
    ],
)
def test_invoke_workflow_round_trip(kwargs: dict[str, Any]) -> None:
    """RouteBuilder.invoke_workflow → YAML → load_pipeline_from_yaml идемпотентен."""

    builder = RouteBuilder.from_(
        f"rt.iw.{kwargs['name']}", source="test:rt"
    ).invoke_workflow(**kwargs)

    initial, rebuilt = _round_trip(builder)

    assert initial == rebuilt


def test_invoke_workflow_rejects_invalid_mode() -> None:
    """Builder валидирует ``mode`` через ``InvokeWorkflowProcessor``."""

    with pytest.raises(ValueError, match="не поддерживается"):
        RouteBuilder.from_("rt.bad", source="test:rt").invoke_workflow(
            "orders.create_with_payment", mode="fire-forget"
        )


def test_invoke_workflow_preserves_defaults_in_spec() -> None:
    """Дефолтные значения не попадают в to_spec (минимальный YAML)."""

    builder = RouteBuilder.from_("rt.min", source="test:rt").invoke_workflow(
        "orders.create_with_payment"
    )
    pipeline = builder.build(validate_actions=False)
    dump = pipeline.to_dict()
    processor_entry = dump["processors"][0]
    assert "invoke_workflow" in processor_entry
    spec = processor_entry["invoke_workflow"]
    assert spec == {"name": "orders.create_with_payment", "mode": "async-api"}


def test_invoke_workflow_async_reply_default_timeout_not_in_spec() -> None:
    """Sprint 8A K3 W11: дефолтный reply_timeout_seconds (60.0) не пишется в spec."""
    builder = RouteBuilder.from_("rt.reply", source="test:rt").invoke_workflow(
        "orders.long", mode="async-reply"
    )
    pipeline = builder.build(validate_actions=False)
    spec = pipeline.to_dict()["processors"][0]["invoke_workflow"]
    assert spec["mode"] == "async-reply"
    assert "reply_timeout_seconds" not in spec


def test_invoke_workflow_async_reply_custom_timeout_in_spec() -> None:
    """Sprint 8A K3 W11: кастомный reply_timeout_seconds попадает в spec."""
    builder = RouteBuilder.from_("rt.reply2", source="test:rt").invoke_workflow(
        "orders.long", mode="async-reply", reply_timeout_seconds=120.0
    )
    pipeline = builder.build(validate_actions=False)
    spec = pipeline.to_dict()["processors"][0]["invoke_workflow"]
    assert spec["mode"] == "async-reply"
    assert spec["reply_timeout_seconds"] == 120.0
