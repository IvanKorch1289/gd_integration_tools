"""Unit tests for PromptComposerProcessor."""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.dsl.engine.processors.ai.promptcomposer_processor import (
    PromptComposerProcessor,
)


class _Message:
    def __init__(self, body: Any = None) -> None:
        self.body = body


class _Exchange:
    def __init__(
        self, body: Any = None, properties: dict[str, Any] | None = None
    ) -> None:
        self.in_message = _Message(body=body)
        self.properties: dict[str, Any] = properties or {}

    def set_property(self, key: str, value: Any) -> None:
        self.properties[key] = value


class _Context:
    pass


class TestPromptComposerProcessor:
    """Tests for :class:`PromptComposerProcessor`."""

    @pytest.mark.asyncio
    async def test_composes_with_dict_body(self) -> None:
        exchange = _Exchange(body={"name": "Alice", "q": "hi"})
        exchange.set_property("vector_results", [{"document": "ctx1"}])
        proc = PromptComposerProcessor(template="Name: {name}\nQ: {q}\nCtx: {context}")
        await proc.process(exchange, _Context())
        prompt = exchange.properties["_composed_prompt"]
        assert "Alice" in prompt
        assert "hi" in prompt
        assert "ctx1" in prompt

    @pytest.mark.asyncio
    async def test_composes_with_string_body(self) -> None:
        exchange = _Exchange(body="plain text")
        proc = PromptComposerProcessor(template="Input: {input}")
        await proc.process(exchange, _Context())
        assert exchange.properties["_composed_prompt"] == "Input: plain text"

    @pytest.mark.asyncio
    async def test_joins_list_context(self) -> None:
        exchange = _Exchange(body={"q": "?"})
        exchange.set_property("vector_results", ["a", "b"])
        proc = PromptComposerProcessor(template="Q: {q}\n{context}")
        await proc.process(exchange, _Context())
        assert "a\n---\nb" in exchange.properties["_composed_prompt"]

    @pytest.mark.asyncio
    async def test_missing_key_raises_keyerror(self) -> None:
        exchange = _Exchange(body={"k": "v"})
        exchange.set_property("vector_results", "")
        proc = PromptComposerProcessor(template="K: {k} M: {missing}")
        with pytest.raises(KeyError):
            await proc.process(exchange, _Context())

    @pytest.mark.asyncio
    async def test_custom_properties(self) -> None:
        exchange = _Exchange(body="x")
        exchange.set_property("my_ctx", "data")
        proc = PromptComposerProcessor(
            template="Ctx: {context}",
            context_property="my_ctx",
            output_property="prompt",
        )
        await proc.process(exchange, _Context())
        assert exchange.properties["prompt"] == "Ctx: data"

    def test_to_spec_defaults(self) -> None:
        proc = PromptComposerProcessor(template="T")
        assert proc.to_spec() == {"compose_prompt": {"template": "T"}}

    def test_to_spec_custom(self) -> None:
        proc = PromptComposerProcessor(
            template="T", context_property="ctx", output_property="out"
        )
        assert proc.to_spec() == {
            "compose_prompt": {"template": "T", "context_property": "ctx"}
        }
