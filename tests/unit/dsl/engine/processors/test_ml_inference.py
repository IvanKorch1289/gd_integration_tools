# ruff: noqa: S101
"""Unit-тесты для ml_inference процессоров.

Покрывает OnnxInferenceProcessor, StreamingLLMProcessor,
EmbeddingProcessor, OutboxProcessor.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.dsl.engine.processors.ml_inference import (
    EmbeddingProcessor,
    OnnxInferenceProcessor,
    OutboxProcessor,
    StreamingLLMProcessor,
)


class _Message:
    def __init__(self, body: Any = None, headers: dict[str, str] | None = None) -> None:
        self.body = body
        self.headers = headers or {}

    def set_body(self, value: Any) -> None:
        self.body = value


class _Exchange:
    def __init__(self, body: Any = None) -> None:
        self.in_message = _Message(body=body)
        self.properties: dict[str, Any] = {}
        self._error: str | None = None
        self.meta = MagicMock(correlation_id="corr-default")

    def get_property(self, key: str) -> Any:
        return self.properties.get(key)

    def set_property(self, key: str, value: Any) -> None:
        self.properties[key] = value

    def fail(self, msg: str) -> None:
        self._error = msg


class _Context:
    pass


@pytest.fixture(autouse=True)
def _clear_onnx_cache() -> None:
    """Очищает LRU-кэш ONNX-моделей между тестами."""
    with OnnxInferenceProcessor._cache_lock:
        OnnxInferenceProcessor._model_cache.clear()


class TestOnnxInferenceProcessorInit:
    def test_default_name(self) -> None:
        proc = OnnxInferenceProcessor(model_path="/m.onnx")
        assert proc.name == "onnx:/m.onnx"

    def test_custom_name(self) -> None:
        proc = OnnxInferenceProcessor(model_path="/m.onnx", name="m")
        assert proc.name == "m"


@pytest.mark.asyncio
class TestOnnxInferenceProcess:
    """``OnnxInferenceProcessor.process``."""

    async def test_import_error_fails_exchange(self) -> None:
        import sys
        from builtins import __import__ as real_import

        proc = OnnxInferenceProcessor(model_path="/m.onnx")
        exchange = _Exchange(body={"features": [1.0]})

        def _fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "onnxruntime":
                raise ImportError("no onnx")
            return real_import(name, *args, **kwargs)

        with (
            patch.dict(sys.modules, {"onnxruntime": None}),
            patch("builtins.__import__", _fake_import),
        ):
            await proc.process(exchange, _Context())

        assert "ONNX session unavailable" in exchange._error

    async def test_load_error_fails_exchange(self) -> None:
        import sys

        proc = OnnxInferenceProcessor(model_path="/m.onnx")
        exchange = _Exchange(body={"features": [1.0]})

        fake_ort = MagicMock()
        fake_ort.InferenceSession.side_effect = RuntimeError("corrupted model")

        with (
            patch.dict(sys.modules, {"onnxruntime": fake_ort}),
            patch("numpy.array", return_value=MagicMock()),
        ):
            await proc.process(exchange, _Context())

        assert "ONNX session unavailable" in exchange._error

    async def test_success(self) -> None:
        import sys

        proc = OnnxInferenceProcessor(model_path="/m.onnx")
        exchange = _Exchange(body={"features": [1.0, 2.0]})

        mock_input = MagicMock()
        mock_input.name = "input"
        mock_session = MagicMock()
        mock_session.get_inputs.return_value = [mock_input]
        mock_session.run.return_value = [MagicMock(tolist=lambda: [0.9, 0.1])]

        fake_ort = MagicMock()
        fake_ort.InferenceSession.return_value = mock_session

        with (
            patch.dict(sys.modules, {"onnxruntime": fake_ort}),
            patch("numpy.array", return_value=MagicMock()),
        ):
            await proc.process(exchange, _Context())

        assert exchange.properties["predictions"] == [0.9, 0.1]
        assert exchange._error is None

    async def test_inference_error_fails_exchange(self) -> None:
        import sys

        proc = OnnxInferenceProcessor(model_path="/m.onnx")
        exchange = _Exchange(body={"features": [1.0]})

        mock_input = MagicMock()
        mock_input.name = "input"
        mock_session = MagicMock()
        mock_session.get_inputs.return_value = [mock_input]
        mock_session.run.side_effect = RuntimeError("infer fail")

        fake_ort = MagicMock()
        fake_ort.InferenceSession.return_value = mock_session

        with (
            patch.dict(sys.modules, {"onnxruntime": fake_ort}),
            patch("numpy.array", return_value=MagicMock()),
        ):
            await proc.process(exchange, _Context())

        assert "ONNX inference failed" in exchange._error

    async def test_non_dict_body(self) -> None:
        import sys

        proc = OnnxInferenceProcessor(model_path="/m.onnx")
        exchange = _Exchange(body=[1.0, 2.0])

        mock_input = MagicMock()
        mock_input.name = "input"
        mock_session = MagicMock()
        mock_session.get_inputs.return_value = [mock_input]
        mock_session.run.return_value = [MagicMock(tolist=lambda: [0.5])]

        fake_ort = MagicMock()
        fake_ort.InferenceSession.return_value = mock_session

        with (
            patch.dict(sys.modules, {"onnxruntime": fake_ort}),
            patch("numpy.array", return_value=MagicMock()),
        ):
            await proc.process(exchange, _Context())

        assert exchange.properties["predictions"] == [0.5]

    async def test_lru_eviction(self) -> None:
        import sys

        proc = OnnxInferenceProcessor(model_path="/m.onnx")
        exchange = _Exchange(body={"features": [1.0]})

        mock_session = MagicMock()
        mock_session.get_inputs.return_value = [MagicMock(name="input")]
        mock_session.run.return_value = [MagicMock(tolist=lambda: [0.1])]

        fake_ort = MagicMock()
        fake_ort.InferenceSession.return_value = mock_session

        with (
            patch.dict(sys.modules, {"onnxruntime": fake_ort}),
            patch("numpy.array", return_value=MagicMock()),
        ):
            # загружаем модель
            await proc.process(exchange, _Context())

        assert "/m.onnx" in OnnxInferenceProcessor._model_cache

        # переполняем кэш
        with OnnxInferenceProcessor._cache_lock:
            for i in range(OnnxInferenceProcessor._MAX_MODELS + 1):
                OnnxInferenceProcessor._model_cache[str(i)] = MagicMock()

        # теперь кэш переполнен, старая модель должна быть вытеснена
        proc2 = OnnxInferenceProcessor(model_path="/new.onnx")
        exchange2 = _Exchange(body={"features": [1.0]})

        mock_session2 = MagicMock()
        mock_session2.get_inputs.return_value = [MagicMock(name="input")]
        mock_session2.run.return_value = [MagicMock(tolist=lambda: [0.2])]

        fake_ort2 = MagicMock()
        fake_ort2.InferenceSession.return_value = mock_session2

        with (
            patch.dict(sys.modules, {"onnxruntime": fake_ort2}),
            patch("numpy.array", return_value=MagicMock()),
        ):
            await proc2.process(exchange2, _Context())

        assert "/new.onnx" in OnnxInferenceProcessor._model_cache


class TestStreamingLLMProcessorInit:
    def test_defaults(self) -> None:
        proc = StreamingLLMProcessor()
        assert proc._provider is None
        assert proc._model == "default"

    def test_custom(self) -> None:
        proc = StreamingLLMProcessor(provider="openai", model="gpt-4")
        assert proc.name == "streaming_llm:openai"


@pytest.mark.asyncio
class TestStreamingLLMProcess:
    """``StreamingLLMProcessor.process``."""

    async def test_import_error_fails_exchange(self) -> None:
        proc = StreamingLLMProcessor()
        exchange = _Exchange(body="hello")

        with patch(
            "src.backend.services.ai.ai_agent.get_ai_agent_service",
            side_effect=ImportError("no ai"),
        ):
            await proc.process(exchange, _Context())

        assert "AI agent unavailable" in exchange._error

    async def test_non_streaming_fallback(self) -> None:
        proc = StreamingLLMProcessor(provider="anthropic")
        exchange = _Exchange(body="prompt")
        exchange.in_message.headers["X-Session-Id"] = "sess-1"

        mock_agent = AsyncMock()
        mock_agent.chat.return_value = "response text"
        del mock_agent.chat_stream

        with (
            patch(
                "src.backend.services.ai.ai_agent.get_ai_agent_service",
                return_value=mock_agent,
            ),
            patch(
                "src.backend.infrastructure.clients.storage.redis.redis_client",
                AsyncMock(),
            ),
        ):
            await proc.process(exchange, _Context())

        assert exchange.in_message.body == "response text"
        mock_agent.chat.assert_awaited_once()

    async def test_streaming_success(self) -> None:
        proc = StreamingLLMProcessor(provider="openai")
        exchange = _Exchange(body="prompt")

        mock_agent = AsyncMock()

        async def _fake_stream(**kwargs: Any) -> Any:
            for chunk in ("hel", "lo"):
                yield chunk

        mock_agent.chat_stream = _fake_stream

        mock_redis = AsyncMock()

        with (
            patch(
                "src.backend.services.ai.ai_agent.get_ai_agent_service",
                return_value=mock_agent,
            ),
            patch(
                "src.backend.infrastructure.clients.storage.redis.redis_client",
                mock_redis,
            ),
        ):
            await proc.process(exchange, _Context())

        assert exchange.in_message.body == "hello"
        # 2 chunks + final empty
        assert mock_redis.add_to_stream.await_count == 3

    async def test_uses_correlation_id_when_no_session_header(self) -> None:
        proc = StreamingLLMProcessor(session_header="X-Session")
        exchange = _Exchange(body="prompt")
        exchange.in_message.headers = {}
        exchange.meta = MagicMock(correlation_id="corr-123")

        mock_agent = AsyncMock()
        mock_agent.chat.return_value = "ok"
        del mock_agent.chat_stream

        mock_redis = AsyncMock()

        with (
            patch(
                "src.backend.services.ai.ai_agent.get_ai_agent_service",
                return_value=mock_agent,
            ),
            patch(
                "src.backend.infrastructure.clients.storage.redis.redis_client",
                mock_redis,
            ),
        ):
            await proc.process(exchange, _Context())

        # проверим что publish_chunk вызван с correlation_id
        call_kwargs = mock_redis.add_to_stream.call_args.kwargs
        assert "llm_stream:corr-123" == call_kwargs["stream_name"]

    async def test_prompt_from_property(self) -> None:
        proc = StreamingLLMProcessor(prompt_property="my_prompt")
        exchange = _Exchange()
        exchange.properties["my_prompt"] = "custom prompt"

        mock_agent = AsyncMock()
        mock_agent.chat.return_value = "ok"
        del mock_agent.chat_stream

        with (
            patch(
                "src.backend.services.ai.ai_agent.get_ai_agent_service",
                return_value=mock_agent,
            ),
            patch(
                "src.backend.infrastructure.clients.storage.redis.redis_client",
                AsyncMock(),
            ),
        ):
            await proc.process(exchange, _Context())

        assert (
            mock_agent.chat.call_args.kwargs["messages"][0]["content"]
            == "custom prompt"
        )

    async def test_exception_fails_exchange(self) -> None:
        proc = StreamingLLMProcessor()
        exchange = _Exchange(body="prompt")

        mock_agent = AsyncMock()
        mock_agent.chat.side_effect = RuntimeError("model down")

        with patch(
            "src.backend.services.ai.ai_agent.get_ai_agent_service",
            return_value=mock_agent,
        ):
            await proc.process(exchange, _Context())

        assert "Streaming LLM failed" in exchange._error


class TestEmbeddingProcessorInit:
    def test_defaults(self) -> None:
        proc = EmbeddingProcessor()
        assert proc._provider is None
        assert proc._model == "all-MiniLM-L6-v2"


@pytest.mark.asyncio
class TestEmbeddingProcess:
    """``EmbeddingProcessor.process``."""

    async def test_empty_text_returns_empty_list(self) -> None:
        proc = EmbeddingProcessor()
        exchange = _Exchange(body={"text": ""})

        await proc.process(exchange, _Context())
        assert exchange.properties["embedding"] == []

    async def test_sentence_transformers_success(self) -> None:
        proc = EmbeddingProcessor(provider="sentence-transformers")
        exchange = _Exchange(body={"text": "hello"})

        mock_rag = MagicMock()
        mock_rag._embed.return_value = MagicMock(tolist=lambda: [0.1, 0.2])

        with patch(
            "src.backend.services.ai.rag_service.get_rag_service", return_value=mock_rag
        ):
            await proc.process(exchange, _Context())

        assert exchange.properties["embedding"] == [0.1, 0.2]

    async def test_sentence_transformers_no_embed_raises(self) -> None:
        proc = EmbeddingProcessor(provider="sentence-transformers")
        exchange = _Exchange(body={"text": "hello"})

        mock_rag = MagicMock()
        del mock_rag._embed

        with patch(
            "src.backend.services.ai.rag_service.get_rag_service", return_value=mock_rag
        ):
            await proc.process(exchange, _Context())

        assert "Embedding failed" in exchange._error

    async def test_openai_success(self) -> None:
        proc = EmbeddingProcessor(provider="openai", model="text-embedding-3")
        exchange = _Exchange(body={"text": "hello"})

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"data": [{"embedding": [0.3, 0.4]}]}

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post.return_value = mock_resp

        with (
            patch("src.backend.core.net.OutboundHttpClient", return_value=mock_client),
            patch.dict("os.environ", {"OPENAI_API_KEY": "sk-123"}),
        ):
            await proc.process(exchange, _Context())

        assert exchange.properties["embedding"] == [0.3, 0.4]
        mock_client.post.assert_awaited_once()

    async def test_openai_missing_key_fails(self) -> None:
        proc = EmbeddingProcessor(provider="openai")
        exchange = _Exchange(body={"text": "hello"})

        with patch.dict("os.environ", {"OPENAI_API_KEY": ""}, clear=True):
            await proc.process(exchange, _Context())

        assert "Embedding failed" in exchange._error

    async def test_ollama_success(self) -> None:
        proc = EmbeddingProcessor(provider="ollama", model="llama2")
        exchange = _Exchange(body={"text": "hello"})

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"embedding": [0.5, 0.6]}

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post.return_value = mock_resp

        with (
            patch("src.backend.core.net.OutboundHttpClient", return_value=mock_client),
            patch.dict("os.environ", {"OLLAMA_URL": "http://ollama:11434"}),
        ):
            await proc.process(exchange, _Context())

        assert exchange.properties["embedding"] == [0.5, 0.6]
        call_args = mock_client.post.call_args
        assert call_args[0][0] == "http://ollama:11434/api/embeddings"

    async def test_non_dict_body(self) -> None:
        proc = EmbeddingProcessor()
        exchange = _Exchange(body="raw text")

        mock_rag = MagicMock()
        mock_rag._embed.return_value = MagicMock(tolist=lambda: [0.1])

        with patch(
            "src.backend.services.ai.rag_service.get_rag_service", return_value=mock_rag
        ):
            await proc.process(exchange, _Context())

        assert exchange.properties["embedding"] == [0.1]

    async def test_exception_fails_exchange(self) -> None:
        proc = EmbeddingProcessor()
        exchange = _Exchange(body={"text": "hello"})

        mock_rag = MagicMock()
        mock_rag._embed.side_effect = RuntimeError("boom")

        with patch(
            "src.backend.services.ai.rag_service.get_rag_service", return_value=mock_rag
        ):
            await proc.process(exchange, _Context())

        assert "Embedding failed" in exchange._error


class TestOutboxProcessorInit:
    def test_invalid_table_name_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid outbox table name"):
            OutboxProcessor(topic="t", table_name="bad;name")

    def test_valid_table_name(self) -> None:
        proc = OutboxProcessor(topic="t", table_name="outbox_messages_v2")
        assert proc._table == "outbox_messages_v2"


@pytest.mark.asyncio
class TestOutboxProcess:
    """``OutboxProcessor.process``."""

    async def test_import_error_fails_exchange(self) -> None:
        import sys
        from builtins import __import__ as real_import

        proc = OutboxProcessor(topic="orders")
        exchange = _Exchange(body={"id": 1})

        def _fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "src.backend.infrastructure.database.database":
                raise ImportError("no db")
            return real_import(name, *args, **kwargs)

        with (
            patch.dict(
                sys.modules, {"src.backend.infrastructure.database.database": None}
            ),
            patch("builtins.__import__", _fake_import),
        ):
            await proc.process(exchange, _Context())

        assert "Database not configured for outbox" in exchange._error

    async def test_success(self) -> None:
        proc = OutboxProcessor(topic="orders.created")
        exchange = _Exchange(body={"id": 42})

        mock_conn = AsyncMock()
        mock_conn_ctx = AsyncMock()
        mock_conn_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_conn_ctx
        mock_db = MagicMock()
        mock_db.get_async_engine.return_value = mock_engine

        with patch(
            "src.backend.infrastructure.database.database.db_initializer", mock_db
        ):
            await proc.process(exchange, _Context())

        assert "outbox_message_id" in exchange.properties
        assert exchange.properties["outbox_topic"] == "orders.created"
        mock_conn.execute.assert_awaited()
        mock_conn.commit.assert_awaited()

    async def test_non_dict_body_wraps(self) -> None:
        proc = OutboxProcessor(topic="events")
        exchange = _Exchange(body="raw")

        mock_conn = AsyncMock()
        mock_conn_ctx = AsyncMock()
        mock_conn_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_conn_ctx
        mock_db = MagicMock()
        mock_db.get_async_engine.return_value = mock_engine

        with patch(
            "src.backend.infrastructure.database.database.db_initializer", mock_db
        ):
            await proc.process(exchange, _Context())

        # проверим что payload содержит wrapped data
        call_args = mock_conn.execute.call_args
        params = call_args[0][1]
        assert '"data":"raw"' in params["payload"]

    async def test_db_error_fails_exchange(self) -> None:
        proc = OutboxProcessor(topic="t")
        exchange = _Exchange(body={})

        mock_conn = AsyncMock()
        mock_conn.execute.side_effect = RuntimeError("db down")
        mock_conn_ctx = AsyncMock()
        mock_conn_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_conn_ctx
        mock_db = MagicMock()
        mock_db.get_async_engine.return_value = mock_engine

        with patch(
            "src.backend.infrastructure.database.database.db_initializer", mock_db
        ):
            await proc.process(exchange, _Context())

        assert "Outbox insert failed" in exchange._error
