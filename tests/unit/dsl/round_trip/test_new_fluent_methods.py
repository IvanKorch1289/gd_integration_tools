"""Round-trip тесты для NEW fluent методов Track A — Step 7.

Покрывает:
    * 5 crud_* aliases (crud_create/read/update/delete/list) → entity_*;
    * 4 NEW процессора (call_function / get_setting / validate_response /
      invoke_workflow) — наличие в pipeline + базовая to_spec round-trip.
"""

# ruff: noqa: S101

from __future__ import annotations

import pytest
import yaml

from src.backend.dsl.builder import RouteBuilder
from src.backend.dsl.engine.processors.entity import (
    EntityCreateProcessor,
    EntityDeleteProcessor,
    EntityGetProcessor,
    EntityListProcessor,
    EntityUpdateProcessor,
)
from src.backend.dsl.engine.processors.function_call import CallFunctionProcessor
from src.backend.dsl.engine.processors.get_setting import GetSettingProcessor
from src.backend.dsl.engine.processors.invoke_workflow import InvokeWorkflowProcessor
from src.backend.dsl.engine.processors.validate_response import (
    ResponseValidatorProcessor,
)
from src.backend.dsl.yaml_loader import load_pipeline_from_yaml


def _round_trip(builder: RouteBuilder) -> tuple[dict, dict]:
    pipeline = builder.build(validate_actions=False)
    dump = pipeline.to_dict()
    yaml_str = yaml.safe_dump(dump, sort_keys=False, allow_unicode=True)
    rebuilt = load_pipeline_from_yaml(yaml_str)
    return dump, rebuilt.to_dict()


# ── crud_* aliases ───────────────────────────────────────────────────


def test_crud_create_alias() -> None:
    """``crud_create`` создаёт ``EntityCreateProcessor`` (alias)."""
    builder = RouteBuilder.from_("rt.crud.create", source="test").crud_create("orders")
    pipeline = builder.build(validate_actions=False)
    assert len(pipeline.processors) == 1
    assert isinstance(pipeline.processors[0], EntityCreateProcessor)


def test_crud_read_alias() -> None:
    builder = RouteBuilder.from_("rt.crud.read", source="test").crud_read(
        "orders", id_from="body.order_id"
    )
    pipeline = builder.build(validate_actions=False)
    assert isinstance(pipeline.processors[0], EntityGetProcessor)


def test_crud_update_alias() -> None:
    builder = RouteBuilder.from_("rt.crud.update", source="test").crud_update("orders")
    pipeline = builder.build(validate_actions=False)
    assert isinstance(pipeline.processors[0], EntityUpdateProcessor)


def test_crud_delete_alias() -> None:
    builder = RouteBuilder.from_("rt.crud.delete", source="test").crud_delete("orders")
    pipeline = builder.build(validate_actions=False)
    assert isinstance(pipeline.processors[0], EntityDeleteProcessor)


def test_crud_list_alias() -> None:
    builder = RouteBuilder.from_("rt.crud.list", source="test").crud_list(
        "orders", page=1, size=10
    )
    pipeline = builder.build(validate_actions=False)
    assert isinstance(pipeline.processors[0], EntityListProcessor)


# ── 4 NEW процессора ─────────────────────────────────────────────────


def test_call_function_builder_adds_processor() -> None:
    builder = RouteBuilder.from_("rt.fn", source="test").call_function(
        "src.backend.dsl.builder:RouteBuilder"
    )
    pipeline = builder.build(validate_actions=False)
    assert isinstance(pipeline.processors[0], CallFunctionProcessor)
    assert pipeline.processors[0].ref == "src.backend.dsl.builder:RouteBuilder"


def test_call_function_rejects_invalid_ref() -> None:
    with pytest.raises(ValueError):
        CallFunctionProcessor("no_colon_here")
    with pytest.raises(ValueError):
        CallFunctionProcessor(":fn_only")
    with pytest.raises(ValueError):
        CallFunctionProcessor("module:")


def test_get_setting_builder_adds_processor() -> None:
    builder = RouteBuilder.from_("rt.gs", source="test").get_setting(
        "ai.openai.model", to="body.model_name", default="gpt-4"
    )
    pipeline = builder.build(validate_actions=False)
    proc = pipeline.processors[0]
    assert isinstance(proc, GetSettingProcessor)
    assert proc.setting_path == "ai.openai.model"
    assert proc.target == "body.model_name"
    assert proc.default == "gpt-4"


def test_get_setting_requires_non_empty_path() -> None:
    with pytest.raises(ValueError):
        GetSettingProcessor("")


def test_validate_response_builder_adds_processor() -> None:
    builder = RouteBuilder.from_("rt.vr", source="test").validate_response(
        on_error="dlq", source="out_body"
    )
    pipeline = builder.build(validate_actions=False)
    proc = pipeline.processors[0]
    assert isinstance(proc, ResponseValidatorProcessor)
    assert proc.on_error == "dlq"


def test_validate_response_rejects_invalid_on_error() -> None:
    with pytest.raises(ValueError):
        ResponseValidatorProcessor(on_error="boom")


def test_invoke_workflow_builder_adds_processor() -> None:
    builder = RouteBuilder.from_("rt.wf", source="test").invoke_workflow(
        "credit_assessment_ai", mode="async-api"
    )
    pipeline = builder.build(validate_actions=False)
    proc = pipeline.processors[0]
    assert isinstance(proc, InvokeWorkflowProcessor)
    assert proc.workflow_name == "credit_assessment_ai"
    assert proc.mode == "async-api"


def test_invoke_workflow_rejects_invalid_mode() -> None:
    with pytest.raises(ValueError):
        InvokeWorkflowProcessor("wf_x", mode="streaming")


# ── round-trip YAML (где to_spec возвращает dict) ────────────────────


def test_get_setting_round_trip_yaml() -> None:
    builder = RouteBuilder.from_("rt.gs.rt", source="test").get_setting(
        "skb.api_url", to="body.api_url"
    )
    dump, rebuilt = _round_trip(builder)
    assert dump == rebuilt


def test_invoke_workflow_round_trip_yaml() -> None:
    builder = RouteBuilder.from_("rt.wf.rt", source="test").invoke_workflow(
        "credit_assessment_ai", mode="sync"
    )
    dump, rebuilt = _round_trip(builder)
    assert dump == rebuilt
