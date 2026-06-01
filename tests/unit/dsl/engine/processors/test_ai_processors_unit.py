"""Unit tests for ai_processors: PromptComposerProcessor, TokenBudgetProcessor,
CacheProcessor, CacheWriteProcessor, LLMParserProcessor, RestorePIIProcessor.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.dsl.engine.processors.ai import (
    CacheProcessor,
    CacheWriteProcessor,
    LLMParserProcessor,
    PromptComposerProcessor,
    RestorePIIProcessor,
    TokenBudgetProcessor,
)


# --------------------------------------------------------------------------- #
# Stubs (same pattern as test_rag_pii_redaction.py)
# --------------------------------------------------------------------------- #

class _Message:
    """Minimal Message stub matching the Message interface used by processors."""

    def __init__(self, body: Any = None) -> None:
        self.body = body
        self.headers: dict[str, Any] = {}

    def set_body(self, value: Any) -> None:
        self.body = value


class _Exchange:
    """Minimal exchange stub: only properties dict + in_message body."""

    def __init__(self, properties: dict[str, Any] | None = None) -> None:
        self.properties = properties or {}
        self.in_message = _Message()
        self.out_message: _Message | None = None

    def set_property(self, key: str, value: Any) -> None:
        self.properties[key] = value

    def set_out(self, body: Any = None, headers: dict[str, Any] | None = None) -> None:
        self.out_message = _Message(body=body)
        if headers:
            self.out_message.headers = headers


class _Context:
    """Stub ExecutionContext — processors don't use it directly in these tests."""


# --------------------------------------------------------------------------- #
# PromptComposerProcessor
# --------------------------------------------------------------------------- #

class TestPromptComposerProcessor:
    """Tests for PromptComposerProcessor (lines 30-69)."""

    @pytest.mark.asyncio
    async def test_composes_prompt_with_dict_body(self) -> None:
        """Template is formatted with body dict + context data."""
        exchange = _Exchange()
        exchange.in_message.body = {"name": "Alice", "query": "hello"}
        exchange.set_property("vector_results", [{"document": "ctx1"}, {"document": "ctx2"}])

        processor = PromptComposerProcessor(
            template="User: {name} asks: {query}\nContext:\n{context}",
            context_property="vector_results",
            output_property="_composed_prompt",
        )
        await processor.process(exchange, _Context())

        prompt = exchange.properties["_composed_prompt"]
        assert "Alice" in prompt
        assert "hello" in prompt
        assert "ctx1" in prompt
        assert "ctx2" in prompt

    @pytest.mark.asyncio
    async def test_composes_prompt_with_string_body(self) -> None:
        """Template is formatted with 'input' key when body is a string."""
        exchange = _Exchange()
        exchange.in_message.body = "plain text query"

        processor = PromptComposerProcessor(
            template="Input: {input}",
        )
        await processor.process(exchange, _Context())

        assert "plain text query" in exchange.properties["_composed_prompt"]

    @pytest.mark.asyncio
    async def test_composes_prompt_with_list_context(self) -> None:
        """List context_property items are joined with --- separator."""
        exchange = _Exchange()
        exchange.in_message.body = {"q": "?"}
        exchange.set_property("vector_results", ["item1", "item2", "item3"])

        processor = PromptComposerProcessor(
            template="Q: {q}\nDocs:\n{context}",
            context_property="vector_results",
        )
        await processor.process(exchange, _Context())

        prompt = exchange.properties["_composed_prompt"]
        assert "item1" in prompt
        assert "---" in prompt
        assert "item2" in prompt
        assert "item3" in prompt

    @pytest.mark.asyncio
    async def test_composes_prompt_missing_context_key(self) -> None:
        """Missing template keys are filled with empty strings (graceful degradation)."""
        exchange = _Exchange()
        exchange.in_message.body = {"known": "val"}
        exchange.set_property("vector_results", "")

        processor = PromptComposerProcessor(
            template="Known: {known} Missing: {notexist}",
        )
        # The fix: missing keys are filled with empty strings, not KeyError
        await processor.process(exchange, _Context())
        assert exchange.properties["_composed_prompt"] == "Known: val Missing: "

    def test_to_spec_includes_template(self) -> None:
        """to_spec returns compose_prompt dict with template."""
        processor = PromptComposerProcessor(
            template="Hello {name}",
            context_property="ctx",
            output_property="out",
        )
        spec = processor.to_spec()
        assert spec == {
            "compose_prompt": {
                "template": "Hello {name}",
                "context_property": "ctx",
            }
        }


# --------------------------------------------------------------------------- #
# TokenBudgetProcessor
# --------------------------------------------------------------------------- #

class TestTokenBudgetProcessor:
    """Tests for TokenBudgetProcessor (lines 237-282)."""

    @pytest.mark.asyncio
    async def test_truncates_by_token_count_when_encoder_available(self) -> None:
        """Text is truncated to max_tokens using tiktoken encoder."""
        exchange = _Exchange()
        exchange.in_message.body = "word " * 2000  # ~2000 tokens if 1 token ~1 word

        processor = TokenBudgetProcessor(max_tokens=100)

        # Patch the _encoder instance variable directly
        mock_encoder = MagicMock()
        mock_encoder.encode.return_value = list(range(2000))
        mock_encoder.decode.return_value = "word " * 100
        processor._encoder = mock_encoder

        await processor.process(exchange, _Context())

        assert "[truncated]" in exchange.in_message.body

    @pytest.mark.asyncio
    async def test_falls_back_to_char_count_when_no_encoder(self) -> None:
        """Without tiktoken, falls back to char-based truncation (max_tokens * 4)."""
        exchange = _Exchange()
        exchange.in_message.body = "x" * 50000  # very long string

        processor = TokenBudgetProcessor(max_tokens=100)
        processor._encoder = None  # Force no encoder

        await processor.process(exchange, _Context())

        # Fallback: max_chars = 100 * 4 = 400
        assert len(exchange.in_message.body) <= 400 + len("\n...[truncated]")

    @pytest.mark.asyncio
    async def test_no_truncation_under_limit(self) -> None:
        """Text under max_tokens is not truncated."""
        exchange = _Exchange()
        exchange.in_message.body = "short text"

        processor = TokenBudgetProcessor(max_tokens=100)
        mock_encoder = MagicMock()
        mock_encoder.encode.return_value = list(range(5))  # only 5 tokens
        mock_encoder.decode.return_value = "short text"
        processor._encoder = mock_encoder

        await processor.process(exchange, _Context())

        assert "short text" in exchange.in_message.body

    @pytest.mark.asyncio
    async def test_truncates_from_property_when_source_property_set(self) -> None:
        """When source_property is set, truncates that property instead of body."""
        exchange = _Exchange()
        exchange.in_message.body = "not used"
        exchange.set_property("long_text", "y " * 5000)

        processor = TokenBudgetProcessor(max_tokens=50, source_property="long_text")
        mock_encoder = MagicMock()
        mock_encoder.encode.return_value = list(range(5000))
        mock_encoder.decode.return_value = "y " * 50
        processor._encoder = mock_encoder

        await processor.process(exchange, _Context())

        assert "[truncated]" in exchange.properties["long_text"]

    @pytest.mark.asyncio
    async def test_ignores_non_string_body(self) -> None:
        """Non-string body is ignored (no-op)."""
        exchange = _Exchange()
        exchange.in_message.body = {"dict": "value"}

        processor = TokenBudgetProcessor(max_tokens=100)
        await processor.process(exchange, _Context())

        # Should remain unchanged
        assert exchange.in_message.body == {"dict": "value"}


# --------------------------------------------------------------------------- #
# CacheProcessor
# --------------------------------------------------------------------------- #

class TestCacheProcessor:
    """Tests for CacheProcessor (lines 671-711)."""

    @pytest.mark.asyncio
    async def test_sets_cache_key_and_ttl_properties(self) -> None:
        """CacheProcessor sets _cache_key and _cache_ttl on exchange."""
        exchange = _Exchange()
        exchange.in_message.body = "test body"

        def key_fn(e: _Exchange) -> str:
            return "my-key"

        processor = CacheProcessor(key_fn=key_fn, ttl_seconds=7200)

        with patch(
            "src.backend.infrastructure.clients.storage.redis.redis_client"
        ) as mock_redis:
            mock_redis.get = AsyncMock(return_value=None)

            await processor.process(exchange, _Context())

        assert exchange.properties["_cache_key"] == "dsl:cache:my-key"
        assert exchange.properties["_cache_ttl"] == 7200

    @pytest.mark.asyncio
    async def test_returns_cached_result_on_hit(self) -> None:
        """When Redis returns cached data, sets body and cached=True."""
        exchange = _Exchange()
        exchange.in_message.body = "original"
        exchange.in_message.headers = {"h": "v"}

        def key_fn(e: _Exchange) -> str:
            return "cached-key"

        processor = CacheProcessor(key_fn=key_fn)

        with patch(
            "src.backend.infrastructure.clients.storage.redis.redis_client"
        ) as mock_redis:
            mock_redis.get = AsyncMock(return_value=b'{"result": "from_cache"}')

            await processor.process(exchange, _Context())

        assert exchange.properties["cached"] is True
        assert exchange.out_message is not None
        assert exchange.out_message.body == {"result": "from_cache"}
        assert exchange.out_message.headers == {"h": "v"}

    @pytest.mark.asyncio
    async def test_sets_cached_false_on_miss(self) -> None:
        """When Redis returns None, sets cached=False."""
        exchange = _Exchange()
        exchange.in_message.body = "original"

        processor = CacheProcessor(key_fn=lambda e: "miss-key")

        with patch(
            "src.backend.infrastructure.clients.storage.redis.redis_client"
        ) as mock_redis:
            mock_redis.get = AsyncMock(return_value=None)

            await processor.process(exchange, _Context())

        assert exchange.properties["cached"] is False

    @pytest.mark.asyncio
    async def test_handles_redis_connection_error(self) -> None:
        """Redis connection errors are caught, cached=False is set."""
        exchange = _Exchange()
        processor = CacheProcessor(key_fn=lambda e: "key")

        with patch(
            "src.backend.infrastructure.clients.storage.redis.redis_client"
        ) as mock_redis:
            mock_redis.get = AsyncMock(side_effect=ConnectionError("no redis"))

            await processor.process(exchange, _Context())

        assert exchange.properties["cached"] is False


# --------------------------------------------------------------------------- #
# CacheWriteProcessor
# --------------------------------------------------------------------------- #

class TestCacheWriteProcessor:
    """Tests for CacheWriteProcessor (lines 714-755)."""

    @pytest.mark.asyncio
    async def test_skips_write_when_cached_is_true(self) -> None:
        """If cached=True (hit), no write is performed."""
        exchange = _Exchange()
        exchange.set_property("cached", True)

        processor = CacheWriteProcessor(key_fn=lambda e: "key")

        with patch(
            "src.backend.infrastructure.clients.storage.redis.redis_client"
        ) as mock_redis:
            mock_redis.set_if_not_exists = AsyncMock()

            await processor.process(exchange, _Context())

        mock_redis.set_if_not_exists.assert_not_called()

    @pytest.mark.asyncio
    async def test_writes_to_redis_on_cache_miss(self) -> None:
        """When cached=False, writes body to Redis."""
        exchange = _Exchange()
        exchange.set_property("cached", False)
        exchange.set_property("_cache_key", "dsl:cache:my-key")
        exchange.in_message.body = {"data": "value"}

        processor = CacheWriteProcessor(
            key_fn=lambda e: "fallback-key", ttl_seconds=3600
        )

        with patch(
            "src.backend.infrastructure.clients.storage.redis.redis_client"
        ) as mock_redis:
            mock_redis.set_if_not_exists = AsyncMock()

            await processor.process(exchange, _Context())

        mock_redis.set_if_not_exists.assert_called_once()
        call = mock_redis.set_if_not_exists.call_args
        assert call.kwargs["key"] == "dsl:cache:my-key"
        assert call.kwargs["ttl"] == 3600

    @pytest.mark.asyncio
    async def test_uses_out_message_body_when_available(self) -> None:
        """Takes body from out_message if present, otherwise in_message.body."""
        exchange = _Exchange()
        exchange.set_property("cached", False)
        exchange.set_property("_cache_key", "dsl:cache:key")
        exchange.in_message.body = "in-body"
        exchange.out_message = _Message(body="out-body")

        processor = CacheWriteProcessor(key_fn=lambda e: "key")

        with patch(
            "src.backend.infrastructure.clients.storage.redis.redis_client"
        ) as mock_redis:
            mock_redis.set_if_not_exists = AsyncMock()

            await processor.process(exchange, _Context())

        call = mock_redis.set_if_not_exists.call_args
        assert "out-body" in str(call.kwargs["value"])

    @pytest.mark.asyncio
    async def test_handles_redis_connection_error_gracefully(self) -> None:
        """Redis errors are caught and swallowed (cache write is best-effort)."""
        exchange = _Exchange()
        exchange.set_property("cached", False)
        exchange.in_message.body = "data"

        processor = CacheWriteProcessor(key_fn=lambda e: "key")

        with patch(
            "src.backend.infrastructure.clients.storage.redis.redis_client"
        ) as mock_redis:
            mock_redis.set_if_not_exists = AsyncMock(
                side_effect=ConnectionError("redis down")
            )

            # Should not raise
            await processor.process(exchange, _Context())


# --------------------------------------------------------------------------- #
# LLMParserProcessor
# --------------------------------------------------------------------------- #

class TestLLMParserProcessor:
    """Tests for LLMParserProcessor (lines 198-234).

    Note: The actual code at line 220 has a Python 2 style exception syntax
    ``except orjson.JSONDecodeError, ValueError:`` which is invalid in Python 3.
    The tests below cover the intended logic assuming the syntax is fixed.
    """

    @pytest.mark.asyncio
    async def test_parses_json_from_text(self) -> None:
        """Extracts JSON between {...} and parses it."""
        exchange = _Exchange()
        exchange.in_message.body = 'Here is the answer: {"status": "ok", "value": 42}'

        processor = LLMParserProcessor(format="json")
        await processor.process(exchange, _Context())

        assert exchange.in_message.body == {"status": "ok", "value": 42}

    @pytest.mark.asyncio
    async def test_parses_plain_text_when_format_not_json(self) -> None:
        """When format=text, returns raw stripped text."""
        exchange = _Exchange()
        exchange.in_message.body = "  plain text answer  "

        processor = LLMParserProcessor(format="text")
        await processor.process(exchange, _Context())

        assert exchange.in_message.body == "plain text answer"

    @pytest.mark.asyncio
    async def test_returns_early_on_non_string_body(self) -> None:
        """Non-string body is returned unchanged."""
        exchange = _Exchange()
        exchange.in_message.body = {"already": "dict"}

        processor = LLMParserProcessor()
        await processor.process(exchange, _Context())

        assert exchange.in_message.body == {"already": "dict"}


# --------------------------------------------------------------------------- #
# RestorePIIProcessor
# --------------------------------------------------------------------------- #

class TestRestorePIIProcessor:
    """Tests for RestorePIIProcessor (lines 597-614)."""

    @pytest.mark.asyncio
    async def test_restores_pii_placeholders(self) -> None:
        """Placeholders in body are replaced with original PII values."""
        exchange = _Exchange()
        exchange.set_property("_pii_mapping", {"[EMAIL_1]": "alice@example.com", "[PHONE_1]": "+7 999 123-45-67"})
        exchange.set_property("_pii_original", "original text")
        exchange.in_message.body = "Contact: [EMAIL_1] or [PHONE_1]"

        processor = RestorePIIProcessor()
        await processor.process(exchange, _Context())

        assert "alice@example.com" in exchange.in_message.body
        assert "+7 999 123-45-67" in exchange.in_message.body

    @pytest.mark.asyncio
    async def test_cleans_up_pii_properties_after_restore(self) -> None:
        """_pii_mapping and _pii_original are removed from properties after restore."""
        exchange = _Exchange()
        exchange.set_property("_pii_mapping", {"[P]": "val"})
        exchange.set_property("_pii_original", "orig")
        exchange.in_message.body = "val"

        processor = RestorePIIProcessor()
        await processor.process(exchange, _Context())

        assert "_pii_mapping" not in exchange.properties
        assert "_pii_original" not in exchange.properties

    @pytest.mark.asyncio
    async def test_noop_when_no_pii_mapping(self) -> None:
        """When _pii_mapping is absent, body is returned unchanged."""
        exchange = _Exchange()
        exchange.in_message.body = "no masking here"

        processor = RestorePIIProcessor()
        await processor.process(exchange, _Context())

        assert exchange.in_message.body == "no masking here"

    @pytest.mark.asyncio
    async def test_handles_non_string_body(self) -> None:
        """Non-string body is converted to string before replacement."""
        exchange = _Exchange()
        exchange.set_property("_pii_mapping", {"[K]": "value"})
        exchange.in_message.body = {"key": "[K]"}  # type: ignore[arg-type]

        processor = RestorePIIProcessor()
        await processor.process(exchange, _Context())

        # Body becomes string with replacement
        assert "value" in exchange.in_message.body
