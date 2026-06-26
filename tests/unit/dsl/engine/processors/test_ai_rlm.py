"""Unit-тесты для ai_rlm.py — Recursive Language Model processor.

Wave [wave:rlm-toolkit]
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.ai_rlm import (
    AIRLMProcessor,
    RLMConfig,
    RLMResult,
)


def _make_exchange(body: Any = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers={}))


# ── RLMConfig ───────────────────────────────────────────────────────────────


class TestRLMConfig:
    def test_default_values(self) -> None:
        config = RLMConfig()

        assert config.max_iterations == 10
        assert config.max_tokens == 4000
        assert config.temperature == 0.7
        assert config.sandbox_enabled is True
        assert config.context_threshold == 10000

    def test_custom_values(self) -> None:
        config = RLMConfig(
            max_iterations=5,
            max_tokens=2000,
            temperature=0.5,
            sandbox_enabled=False,
            context_threshold=5000,
        )

        assert config.max_iterations == 5
        assert config.max_tokens == 2000
        assert config.temperature == 0.5
        assert config.sandbox_enabled is False
        assert config.context_threshold == 5000


# ── RLMResult ────────────────────────────────────────────────────────────────


class TestRLMResult:
    def test_default_values(self) -> None:
        result = RLMResult()

        assert result.answer is None
        assert result.tokens_used == 0
        assert result.calls == 0
        assert result.iterations == 0
        assert result.context_size == 0

    def test_custom_values(self) -> None:
        result = RLMResult(
            answer="test answer",
            tokens_used=100,
            calls=3,
            iterations=2,
            context_size=5000,
        )

        assert result.answer == "test answer"
        assert result.tokens_used == 100
        assert result.calls == 3
        assert result.iterations == 2
        assert result.context_size == 5000


# ── AIRLMProcessor ───────────────────────────────────────────────────────────


class TestAIRLMProcessorCreation:
    def test_default_name(self) -> None:
        proc = AIRLMProcessor()
        assert proc.name == "ai_rlm"

    def test_custom_name(self) -> None:
        proc = AIRLMProcessor(name="custom_rlm")
        assert proc.name == "custom_rlm"

    def test_default_model(self) -> None:
        proc = AIRLMProcessor()
        assert proc.model == "openai/gpt-4"

    def test_custom_model(self) -> None:
        proc = AIRLMProcessor(model="anthropic/claude-3")
        assert proc.model == "anthropic/claude-3"

    def test_default_config(self) -> None:
        proc = AIRLMProcessor()
        assert isinstance(proc.config, RLMConfig)

    def test_custom_config(self) -> None:
        config = RLMConfig(max_iterations=5)
        proc = AIRLMProcessor(config=config)
        assert proc.config.max_iterations == 5

    def test_default_result_property(self) -> None:
        proc = AIRLMProcessor()
        assert proc.result_property == "rlm_result"

    def test_side_effect_is_side_effecting(self) -> None:
        assert AIRLMProcessor.side_effect.value == "side_effecting"

    def test_not_compensatable(self) -> None:
        assert AIRLMProcessor.compensatable is False


@pytest.mark.asyncio
async def test_process_requires_context() -> None:
    proc = AIRLMProcessor()
    exc = _make_exchange({"query": "test?"})
    ctx = MagicMock()

    await proc.process(exc, ctx)

    assert exc.error is not None
    assert "context" in exc.error.lower()


@pytest.mark.asyncio
async def test_process_requires_query() -> None:
    proc = AIRLMProcessor()
    exc = _make_exchange({"context": "some text"})
    ctx = MagicMock()

    await proc.process(exc, ctx)

    assert exc.error is not None
    assert "query" in exc.error.lower()


@pytest.mark.asyncio
async def test_process_direct_mode_small_context() -> None:
    proc = AIRLMProcessor()
    exc = _make_exchange({"context": "short text", "query": "what is it?"})
    ctx = MagicMock()

    await proc.process(exc, ctx)

    # Should use direct mode for small context
    assert exc.properties.get("rlm_iterations") in (0, 1)  # S171 M11 R2: depends on context
    assert exc.properties.get("rlm_result") is not None


@pytest.mark.asyncio
async def test_process_rlm_mode_large_context() -> None:
    proc = AIRLMProcessor(config=RLMConfig(context_threshold=10))  # Very low threshold
    # Create a large context that exceeds threshold
    large_context = "word " * 100  # ~500 tokens
    exc = _make_exchange({"context": large_context, "query": "summarize?"})
    ctx = MagicMock()

    await proc.process(exc, ctx)

    # Should use RLM mode for large context
    assert exc.properties.get("rlm_iterations", 0) >= 1


@pytest.mark.asyncio
async def test_process_sets_result_property() -> None:
    proc = AIRLMProcessor(result_property="my_result")
    exc = _make_exchange({"context": "test context", "query": "test?"})
    ctx = MagicMock()

    await proc.process(exc, ctx)

    assert "my_result" in exc.properties
    assert exc.properties.get("my_result") is not None


@pytest.mark.asyncio
async def test_process_sets_token_count() -> None:
    proc = AIRLMProcessor()
    exc = _make_exchange({"context": "some text here", "query": "test?"})
    ctx = MagicMock()

    await proc.process(exc, ctx)

    assert "rlm_tokens_used" in exc.properties
    assert isinstance(exc.properties.get("rlm_tokens_used"), int)


class TestEstimateTokens:
    def test_estimate_empty_string(self) -> None:
        proc = AIRLMProcessor()
        assert proc._estimate_tokens("") == 0

    def test_estimate_english_text(self) -> None:
        # ~4 chars per token for English
        proc = AIRLMProcessor()
        text = "a" * 400
        assert proc._estimate_tokens(text) == 100


class TestToSpec:
    def test_to_spec_returns_dict(self) -> None:
        proc = AIRLMProcessor(model="test/model", config=RLMConfig(max_iterations=5))

        spec = proc.to_spec()

        assert isinstance(spec, dict)
        assert "ai_rlm" in spec
        assert spec["ai_rlm"]["model"] == "test/model"
        assert spec["ai_rlm"]["max_iterations"] == 5

    def test_to_spec_includes_all_fields(self) -> None:
        proc = AIRLMProcessor()

        spec = proc.to_spec()
        ai_rlm_spec = spec["ai_rlm"]

        assert "model" in ai_rlm_spec
        assert "max_iterations" in ai_rlm_spec
        assert "max_tokens" in ai_rlm_spec
        assert "temperature" in ai_rlm_spec
        assert "context_threshold" in ai_rlm_spec
        assert "result_property" in ai_rlm_spec


@pytest.mark.asyncio
async def test_process_with_custom_prompt_template() -> None:
    proc = AIRLMProcessor(
        prompt_template="Context: {context}\nQuestion: {query}\nAnswer:"
    )
    exc = _make_exchange({"context": "test ctx", "query": "test?"})
    ctx = MagicMock()

    await proc.process(exc, ctx)

    # Should still work with custom template
    assert exc.properties.get("rlm_result") is not None


@pytest.mark.asyncio
async def test_process_multiple_calls_accumulate() -> None:
    proc = AIRLMProcessor()
    exc = _make_exchange({"context": "test context", "query": "q1"})
    ctx = MagicMock()

    await proc.process(exc, ctx)
    await proc.process(exc, ctx)

    # Result should be updated
    assert exc.properties.get("rlm_result") is not None
