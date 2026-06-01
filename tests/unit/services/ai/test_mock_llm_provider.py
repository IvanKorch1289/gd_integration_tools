"""Unit-тесты для MockLLMProvider (S10 K4 W1)."""

from __future__ import annotations

import pytest

from src.backend.services.ai.mock_llm_provider import MockLLMProvider


@pytest.mark.asyncio
async def test_chat_returns_canned_response_when_set() -> None:
    p = MockLLMProvider(canned_response="HELLO")
    resp = await p.chat([{"role": "user", "content": "hi"}])
    assert p.extract_text(resp) == "HELLO"
    assert resp["usage"] == {"input_tokens": 0, "output_tokens": 0}


@pytest.mark.asyncio
async def test_chat_is_deterministic_for_same_input() -> None:
    p = MockLLMProvider()
    msgs = [{"role": "user", "content": "test"}]
    r1 = await p.chat(msgs)
    r2 = await p.chat(msgs)
    assert r1["id"] == r2["id"]
    assert p.extract_text(r1) == p.extract_text(r2)


@pytest.mark.asyncio
async def test_chat_different_input_gives_different_id() -> None:
    p = MockLLMProvider()
    r1 = await p.chat([{"role": "user", "content": "x"}])
    r2 = await p.chat([{"role": "user", "content": "y"}])
    assert r1["id"] != r2["id"]


@pytest.mark.asyncio
async def test_chat_with_tools_returns_tool_use_block() -> None:
    p = MockLLMProvider(tool_arguments={"q": "moscow"})
    tools = [{"name": "weather", "description": "get weather"}]
    resp = await p.chat(
        [{"role": "user", "content": "погода?"}], tools=tools
    )
    assert resp["content"][0]["type"] == "tool_use"
    assert resp["content"][0]["name"] == "weather"
    assert resp["content"][0]["input"] == {"q": "moscow"}


@pytest.mark.asyncio
async def test_embeddings_zero_vector_correct_dim() -> None:
    p = MockLLMProvider(embedding_dim=8)
    out = await p.embeddings(["a", "b", "c"])
    assert out == [[0.0] * 8, [0.0] * 8, [0.0] * 8]


def test_provider_name_constant() -> None:
    assert MockLLMProvider.name == "mock-llm"


@pytest.mark.asyncio
async def test_cost_zero_in_all_responses() -> None:
    """cost_usd derivable from usage: 0 input + 0 output = 0."""
    p = MockLLMProvider()
    resp = await p.chat([{"role": "user", "content": "x"}])
    usage = resp["usage"]
    assert usage["input_tokens"] == 0
    assert usage["output_tokens"] == 0
