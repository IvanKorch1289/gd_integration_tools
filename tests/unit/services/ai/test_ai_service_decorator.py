# ruff: noqa: S101
"""Sprint 14 K4 W1 — unit-тесты ``@ai_service`` decorator."""

from __future__ import annotations

import pytest

from src.backend.services.ai.decorators import AIServiceSpec, ai_service
from src.backend.services.ai.registry import (
    AIPluginRegistry,
    get_ai_plugin_registry,
)


@pytest.fixture()
def fresh_registry() -> AIPluginRegistry:
    reg = AIPluginRegistry()
    return reg


@pytest.mark.asyncio
async def test_decorator_registers_spec(fresh_registry: AIPluginRegistry) -> None:
    @ai_service(
        name="demo.score",
        model="gpt-4o-mini",
        capabilities=["ai.llm.openai"],
        registry=fresh_registry,
    )
    async def score(payload: dict) -> dict:
        """Оценить заявку."""
        return {"score": 1.0, "payload": payload}

    assert fresh_registry.get("demo.score") is not None
    result = await score({"a": 1})
    assert result == {"score": 1.0, "payload": {"a": 1}}


def test_decorator_rejects_sync_function(fresh_registry: AIPluginRegistry) -> None:
    with pytest.raises(ValueError, match="async function"):

        @ai_service(name="demo.sync", registry=fresh_registry)
        def sync_func() -> None:
            pass


def test_decorator_rejects_empty_name(fresh_registry: AIPluginRegistry) -> None:
    with pytest.raises(ValueError, match="non-empty"):

        @ai_service(name="", registry=fresh_registry)
        async def x() -> None:
            pass


@pytest.mark.asyncio
async def test_spec_serialisation(fresh_registry: AIPluginRegistry) -> None:
    @ai_service(
        name="demo.classify",
        model="claude-haiku",
        capabilities=["ai.llm.anthropic"],
        description="Classify documents.",
        registry=fresh_registry,
    )
    async def classify(doc: str) -> str:
        return doc

    spec = fresh_registry.get("demo.classify")
    assert spec is not None
    payload = spec.to_dict()
    assert payload["name"] == "demo.classify"
    assert payload["model"] == "claude-haiku"
    assert payload["capabilities"] == ["ai.llm.anthropic"]
    assert "doc" in payload["signature"]


def test_registry_clear_resets_state(fresh_registry: AIPluginRegistry) -> None:
    @ai_service(name="demo.clear_test", registry=fresh_registry)
    async def x() -> None:
        pass

    assert fresh_registry.get("demo.clear_test") is not None
    fresh_registry.clear()
    assert fresh_registry.get("demo.clear_test") is None


def test_singleton_registry_returns_same_instance() -> None:
    r1 = get_ai_plugin_registry()
    r2 = get_ai_plugin_registry()
    assert r1 is r2


@pytest.mark.asyncio
async def test_overwrite_same_name(fresh_registry: AIPluginRegistry) -> None:
    @ai_service(name="demo.dup", model="m1", registry=fresh_registry)
    async def f1() -> str:
        return "v1"

    @ai_service(name="demo.dup", model="m2", registry=fresh_registry)
    async def f2() -> str:
        return "v2"

    spec = fresh_registry.get("demo.dup")
    assert spec is not None
    assert spec.model == "m2"


def test_aiservicespec_dataclass_fields() -> None:
    spec = AIServiceSpec(
        name="x",
        model=None,
        capabilities=(),
        description="",
        function=lambda: None,  # type: ignore[arg-type]
        signature_repr="()",
    )
    assert spec.name == "x"
    assert spec.capabilities == ()
