"""Tests for S127 W4 — Anthropic Prompt Cache (TD-022 partial).

Covers:
- is_anthropic_cacheable: model detection (cacheable vs not)
- inject_prompt_cache: cache_control injection в user/system messages
- inject_prompt_cache: no-op для non-cacheable моделей
- inject_prompt_cache: idempotency / preserves original messages structure
- TTL: respects PromptCacheConfig.ttl_seconds
"""

from __future__ import annotations

import pytest

from src.backend.infrastructure.ai.prompt_cache_middleware import (
    PromptCacheConfig,
    inject_prompt_cache,
    is_anthropic_cacheable,
)


# ---------------------------------------------------------------------------
# is_anthropic_cacheable tests
# ---------------------------------------------------------------------------


class TestIsAnthropicCacheable:
    @pytest.mark.parametrize(
        "model",
        [
            "anthropic/claude-3-5-sonnet-20241022",
            "anthropic/claude-3-5-sonnet-latest",
            "anthropic/claude-3-5-haiku-20241022",
            "anthropic/claude-3-7-sonnet-20250219",
            "anthropic/claude-sonnet-4-20250514",
            "anthropic/claude-opus-4-20250514",
            "anthropic/claude-haiku-4-20250514",
        ],
    )
    def test_cacheable_models(self, model: str) -> None:
        assert is_anthropic_cacheable(model) is True

    @pytest.mark.parametrize(
        "model",
        [
            "openai/gpt-4-turbo",
            "openai/gpt-4o",
            "anthropic/claude-3-haiku-20240307",  # 3-haiku NOT cacheable
            "anthropic/claude-2.1",  # old claude-2
            "",
            "claude-3-5-sonnet",  # no anthropic/ prefix
        ],
    )
    def test_non_cacheable_models(self, model: str) -> None:
        assert is_anthropic_cacheable(model) is False


# ---------------------------------------------------------------------------
# inject_prompt_cache tests
# ---------------------------------------------------------------------------


class TestInjectPromptCache:
    def test_no_op_for_openai(self) -> None:
        """OpenAI models: cache_control не инжектится."""
        messages = [{"role": "user", "content": "Hello"}]
        result = inject_prompt_cache(messages, "openai/gpt-4-turbo")
        assert result == messages

    def test_injects_user_content_for_anthropic(self) -> None:
        """Anthropic user content → list с cache_control."""
        messages = [{"role": "user", "content": "Hello, world!"}]
        result = inject_prompt_cache(
            messages, "anthropic/claude-3-5-sonnet-20241022"
        )
        assert result != messages  # new list
        assert result[0]["role"] == "user"
        content = result[0]["content"]
        assert isinstance(content, list)
        assert content[0]["type"] == "text"
        assert content[0]["text"] == "Hello, world!"
        assert content[0]["cache_control"] == {"type": "ephemeral", "ttl": 300}

    def test_injects_system_message(self) -> None:
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hi"},
        ]
        result = inject_prompt_cache(
            messages, "anthropic/claude-3-5-sonnet-20241022"
        )
        sys_content = result[0]["content"]
        assert isinstance(sys_content, list)
        assert sys_content[0]["cache_control"]["type"] == "ephemeral"

    def test_appends_to_existing_list_content(self) -> None:
        """Multi-block content: cache_control добавлен к последнему блоку."""
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "block 1"},
                    {"type": "text", "text": "block 2"},
                ],
            }
        ]
        result = inject_prompt_cache(
            messages, "anthropic/claude-3-5-sonnet-20241022"
        )
        last_block = result[0]["content"][-1]
        assert last_block["text"] == "block 2"
        assert "cache_control" in last_block
        # First block unchanged.
        assert "cache_control" not in result[0]["content"][0]

    def test_disabled_config_no_op(self) -> None:
        messages = [{"role": "user", "content": "Hello"}]
        config = PromptCacheConfig(enabled=False)
        result = inject_prompt_cache(
            messages, "anthropic/claude-3-5-sonnet-20241022", config=config
        )
        assert result == messages

    def test_custom_ttl(self) -> None:
        messages = [{"role": "user", "content": "Hello"}]
        config = PromptCacheConfig(ttl_seconds=600)
        result = inject_prompt_cache(
            messages, "anthropic/claude-3-5-sonnet-20241022", config=config
        )
        cache_control = result[0]["content"][0]["cache_control"]
        assert cache_control["ttl"] == 600

    def test_apply_to_user_content_false(self) -> None:
        """Когда apply_to_user_content=False, system content всё равно инжектится."""
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "user"},
        ]
        config = PromptCacheConfig(apply_to_user_content=False)
        result = inject_prompt_cache(
            messages, "anthropic/claude-3-5-sonnet-20241022", config=config
        )
        # System has cache_control.
        assert "cache_control" in result[0]["content"][0]
        # User content remains as string.
        assert result[1]["content"] == "user"

    def test_does_not_mutate_original(self) -> None:
        """Оригинальный messages list не модифицируется."""
        messages = [{"role": "user", "content": "Hello"}]
        original = list(messages)
        inject_prompt_cache(messages, "anthropic/claude-3-5-sonnet-20241022")
        assert messages == original

    def test_empty_messages(self) -> None:
        result = inject_prompt_cache([], "anthropic/claude-3-5-sonnet-20241022")
        assert result == []


# ---------------------------------------------------------------------------
# Integration smoke test (no real LLM call)
# ---------------------------------------------------------------------------


class TestIntegrationWithLlmMixin:
    """Smoke: verify that llm_mixin uses inject_prompt_cache."""

    def test_llm_mixin_imports_inject_prompt_cache(self) -> None:
        """Verify the llm_mixin module imports the new function."""
        import inspect

        from src.backend.core.ai.gateway_pipeline_mixin import llm_mixin

        source = inspect.getsource(llm_mixin)
        assert "inject_prompt_cache" in source
