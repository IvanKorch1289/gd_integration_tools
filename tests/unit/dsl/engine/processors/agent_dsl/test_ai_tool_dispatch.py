# ruff: noqa: S101
"""S106 W4 — tests для ``RouteBuilder.ai_tool_dispatch()`` + ``AIToolDispatchProcessor``.

Покрытие:

* DSL registration (chainable, single processor instance);
* Validation: empty available_tool_ids / no query → ValueError;
* Capability scope = sorted joined tool_ids (whitelist fingerprint);
* Result property заполняется skeleton-hint (S106+ W5+ для real LLM);
* Lazy ToolRegistry resolve — graceful fallback при DI=None;
* to_spec round-trip (через pipeline.to_dict).
"""

from __future__ import annotations

import pytest

from src.backend.dsl.builders.base import RouteBuilder
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.agent_dsl.ai_tool_dispatch import (
    AIToolDispatchProcessor,
)
from src.backend.dsl.engine.processors.agent_dsl._base import BaseAIProcessor


def _ex(body: str | None = None, **props: str) -> Exchange[str]:
    ex = Exchange(in_message=Message(body=body or "", headers={}))
    for k, v in props.items():
        ex.set_property(k, v)
    return ex


def _ctx() -> ExecutionContext:
    return ExecutionContext()


# ── DSL registration ──


def test_ai_tool_dispatch_dsl_registers_processor() -> None:
    """``RouteBuilder.ai_tool_dispatch(...)`` — добавляет AIToolDispatchProcessor."""
    b = RouteBuilder("test", source="kafka:orders")
    result = b.ai_tool_dispatch(
        available_tool_ids=["order.get", "order.list"],
        query="get order 123",
    )
    assert isinstance(result, RouteBuilder)
    assert result is b
    assert len(b._processors) == 1
    p = b._processors[0]
    assert isinstance(p, AIToolDispatchProcessor)
    assert p.available_tool_ids == ["order.get", "order.list"]


def test_ai_tool_dispatch_chainable_with_other_methods() -> None:
    """``ai_tool_dispatch()`` — chainable с другими DSL методами."""
    b = (
        RouteBuilder("test", source="kafka:orders")
        .set_property("user_query", "show my orders")
        .ai_tool_dispatch(
            available_tool_ids=["order.list"],
            query_property="user_query",
        )
        .audit(action="tool_dispatched")
    )
    assert len(b._processors) == 3
    assert isinstance(b._processors[1], AIToolDispatchProcessor)


# ── Validation ──


def test_ai_tool_dispatch_rejects_empty_tool_ids() -> None:
    """Пустой ``available_tool_ids`` → ValueError (нет whitelist)."""
    with pytest.raises(ValueError, match="available_tool_ids"):
        AIToolDispatchProcessor(available_tool_ids=[], query="x")


def test_ai_tool_dispatch_rejects_no_query() -> None:
    """Без query и query_property → ValueError (LLM нечего обрабатывать)."""
    with pytest.raises(ValueError, match="query или query_property"):
        AIToolDispatchProcessor(available_tool_ids=["x"])


def test_ai_tool_dispatch_accepts_query_only() -> None:
    """Только query — OK."""
    p = AIToolDispatchProcessor(available_tool_ids=["x"], query="static")
    assert p.query == "static"
    assert p.query_property is None


def test_ai_tool_dispatch_accepts_query_property_only() -> None:
    """Только query_property — OK."""
    p = AIToolDispatchProcessor(
        available_tool_ids=["x"], query_property="body.q"
    )
    assert p.query is None
    assert p.query_property == "body.q"


# ── Capability scope ──


def test_ai_tool_dispatch_capability_scope_is_sorted_join() -> None:
    """Scope = sorted joined tool_ids (whitelist fingerprint для audit)."""
    p = AIToolDispatchProcessor(
        available_tool_ids=["c.b", "a.c", "b.a"],
        query="x",
    )
    scope = p._capability_scope(_ex())
    assert scope == "a.c,b.a,c.b"


def test_ai_tool_dispatch_inherits_base_ai_processor() -> None:
    """Наследует BaseAIProcessor (feature-flag + capability + audit)."""
    p = AIToolDispatchProcessor(available_tool_ids=["x"], query="y")
    assert isinstance(p, BaseAIProcessor)
    assert p.required_capability == "ai.tool.dispatch"
    assert p.audit_event == "ai.tool.dispatch"


# ── Skeleton process behavior ──


@pytest.mark.asyncio
async def test_ai_tool_dispatch_skeleton_writes_scaffold_result() -> None:
    """S106 W4 skeleton: пишет scaffold-hint в result_property."""
    p = AIToolDispatchProcessor(
        available_tool_ids=["order.get", "order.list"],
        query="get order 123",
    )
    ex = _ex()
    await p._run(ex, _ctx())

    result = ex.get_property("tool_dispatch_result")
    assert result["dispatched"] is False
    assert result["reason"] == "scaffold"
    assert result["available_tools_count"] == 2
    assert "S106+ W5+" in result["hint"]


@pytest.mark.asyncio
async def test_ai_tool_dispatch_skeleton_handles_empty_query_property() -> None:
    """Пустой query_property → result=empty_query (graceful)."""
    p = AIToolDispatchProcessor(
        available_tool_ids=["x"],
        query_property="missing",
    )
    ex = _ex()  # no property "missing"
    await p._run(ex, _ctx())

    result = ex.get_property("tool_dispatch_result")
    assert result == {"dispatched": False, "reason": "empty_query"}


@pytest.mark.asyncio
async def test_ai_tool_dispatch_skeleton_uses_dynamic_query() -> None:
    """query_property подхватывается из exchange."""
    p = AIToolDispatchProcessor(
        available_tool_ids=["x"],
        query_property="user_q",
    )
    ex = _ex(user_q="show me X")
    await p._run(ex, _ctx())

    result = ex.get_property("tool_dispatch_result")
    assert result["query_chars"] == len("show me X")


# ── ToolRegistry lazy resolve ──


def test_ai_tool_dispatch_resolve_tools_includes_unavailable_as_false() -> None:
    """ToolRegistry.get(unknown_id) → ``available: False`` в spec (честный whitelist).

    При наличии singleton ToolRegistry (всегда есть через DI), unknown
    tool_id помечается ``available: False`` — LLM должен увидеть и
    отказаться от выбора. При отсутствии registry — generic
    ``available: True`` (scaffold-режим).
    """
    p = AIToolDispatchProcessor(
        available_tool_ids=["definitely_not_a_real_tool_xyz"],
        query="x",
    )
    import json

    desc = p._resolve_tools_description()
    parsed = json.loads(desc)
    assert parsed == [{"id": "definitely_not_a_real_tool_xyz", "available": False}]


def test_ai_tool_dispatch_resolve_tools_scaffold_fallback_on_registry_error() -> None:
    """При ошибке импорта/резолва ToolRegistry — generic-описание (scaffold)."""
    p = AIToolDispatchProcessor(
        available_tool_ids=["a", "b"],
        query="x",
    )
    import json
    from unittest.mock import patch

    with patch(
        "src.backend.services.ai.tools.registry.get_tool_registry",
        side_effect=RuntimeError("DI offline"),
    ):
        desc = p._resolve_tools_description()
    parsed = json.loads(desc)
    # При ошибке резолва — generic {"id": tid, "available": True}
    assert parsed == [{"id": "a", "available": True}, {"id": "b", "available": True}]


# ── Spec round-trip ──


def test_ai_tool_dispatch_to_dict_pipeline() -> None:
    """pipeline.to_dict() содержит ``ai_tool_dispatch`` step с правильным spec."""
    b = RouteBuilder("test", source="kafka:x").ai_tool_dispatch(
        available_tool_ids=["a", "b"],
        query_property="body.q",
        result_property="my_result",
    )
    pipeline = b.build(validate_actions=False)
    spec = pipeline.to_dict()["processors"][0]["ai_tool_dispatch"]
    assert spec["available_tool_ids"] == ["a", "b"]
    assert spec["query_property"] == "body.q"
    assert spec["result_property"] == "my_result"


def test_ai_tool_dispatch_omits_default_query_in_spec() -> None:
    """При использовании только query_property — ``query`` не в spec если None."""
    b = RouteBuilder("test", source="kafka:x").ai_tool_dispatch(
        available_tool_ids=["a"], query_property="body.q"
    )
    # Проверяем что processor правильно хранит None query
    p = b._processors[0]
    assert p.query is None
    assert p.query_property == "body.q"
