"""ML Inference processors — ONNX + streaming LLM + embeddings + outbox.

CPU-only inference через ONNX Runtime. Graceful fallback если onnxruntime
не установлен (процессор просто пробрасывает body).
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from threading import Lock
from typing import Any

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

__all__ = (
    "OnnxInferenceProcessor",
    "StreamingLLMProcessor",
    "EmbeddingProcessor",
    "OutboxProcessor",
)

logger = logging.getLogger("dsl.ml_inference")


class OnnxInferenceProcessor(BaseProcessor):
    """ONNX model inference (CPU-only).

    Loads model once (singleton per path), выполняет inference.

    Usage::
        .onnx_infer(model_path="/models/classifier.onnx",
                    input_key="features", output_property="predictions")
    """

    # LRU-кэш моделей: ограничен размером, чтобы избежать OOM при большом
    # числе разных моделей. Потокобезопасен через Lock (модели могут загружаться
    # параллельно из разных pipeline'ов).
    _MAX_MODELS: int = 8
    _model_cache: OrderedDict[str, Any] = OrderedDict()
    _cache_lock: Lock = Lock()

    def __init__(
        self,
        *,
        model_path: str,
        input_key: str = "features",
        output_property: str = "predictions",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"onnx:{model_path}")
        self._path = model_path
        self._input_key = input_key
        self._output = output_property

    def _get_session(self) -> Any:
        """Возвращает ONNX-сессию с LRU-вытеснением старых моделей."""
        with self._cache_lock:
            if self._path in self._model_cache:
                # move-to-end помечает как "недавно использованную"
                self._model_cache.move_to_end(self._path)
                return self._model_cache[self._path]

        try:
            import onnxruntime as ort

            session = ort.InferenceSession(
                self._path, providers=["CPUExecutionProvider"]
            )
        except ImportError:
            logger.warning("onnxruntime not installed, ONNX inference disabled")
            return None
        except Exception as exc:
            logger.error("ONNX model load failed: %s", exc)
            return None

        with self._cache_lock:
            self._model_cache[self._path] = session
            # Вытесняем самую старую модель при переполнении кэша
            while len(self._model_cache) > self._MAX_MODELS:
                evicted_path, _ = self._model_cache.popitem(last=False)
                logger.info("ONNX LRU eviction: %s", evicted_path)
        return session

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        session = self._get_session()
        if session is None:
            exchange.fail("ONNX session unavailable")
            return

        body = exchange.in_message.body
        features = body.get(self._input_key) if isinstance(body, dict) else body

        try:
            import numpy as np

            arr = np.array(features, dtype=np.float32)

            input_name = session.get_inputs()[0].name
            outputs = session.run(None, {input_name: arr})
            preds = outputs[0].tolist() if hasattr(outputs[0], "tolist") else outputs

            exchange.set_property(self._output, preds)
        except Exception as exc:
            exchange.fail(f"ONNX inference failed: {exc}")


class StreamingLLMProcessor(BaseProcessor):
    """Streaming LLM response — чанки отправляются через Redis stream.

    Для WebSocket/SSE UI: клиенты подписаны на канал `llm_stream:{session_id}`
    и получают chunks в реальном времени.

    Usage::
        .streaming_llm(provider="anthropic", session_header="X-Session-Id")
    """

    def __init__(
        self,
        *,
        provider: str | None = None,
        model: str = "default",
        session_header: str = "X-Session-Id",
        prompt_property: str = "_composed_prompt",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"streaming_llm:{provider or 'default'}")
        self._provider = provider
        self._model = model
        self._session_header = session_header
        self._prompt_property = prompt_property

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        prompt = exchange.properties.get(self._prompt_property)
        if prompt is None:
            body = exchange.in_message.body
            prompt = body if isinstance(body, str) else str(body)

        session_id = exchange.in_message.headers.get(self._session_header, "")
        if not session_id:
            session_id = exchange.meta.correlation_id

        try:
            from src.backend.services.ai.ai_agent import get_ai_agent_service

            agent = get_ai_agent_service()

            # Проверяем что у агента есть streaming (иначе fallback в non-streaming)
            if not hasattr(agent, "chat_stream"):
                result = await agent.chat(
                    messages=[{"role": "user", "content": prompt}],
                    provider=self._provider,
                    model=self._model,
                )
                await self._publish_chunk(session_id, result, is_final=True)
                exchange.in_message.set_body(result)
                return

            chunks: list[str] = []
            async for chunk in agent.chat_stream(
                messages=[{"role": "user", "content": prompt}],
                provider=self._provider,
                model=self._model,
            ):
                chunks.append(str(chunk))
                await self._publish_chunk(session_id, chunk, is_final=False)

            await self._publish_chunk(session_id, "", is_final=True)
            exchange.in_message.set_body("".join(chunks))

        except ImportError as exc:
            exchange.fail(f"AI agent unavailable: {exc}")
        except Exception as exc:
            exchange.fail(f"Streaming LLM failed: {exc}")

    async def _publish_chunk(
        self, session_id: str, content: Any, *, is_final: bool
    ) -> None:
        try:
            from src.backend.infrastructure.clients.storage.redis import redis_client

            await redis_client.add_to_stream(
                stream_name=f"llm_stream:{session_id}",
                data={
                    "content": str(content)[:4096],
                    "final": "1" if is_final else "0",
                },
            )
        except Exception as exc:
            logger.debug("Stream publish failed: %s", exc)


class EmbeddingProcessor(BaseProcessor):
    """Унифицированный embedding generation — OpenAI/SentenceTransformers/Ollama.

    Provider выбирается через ENV EMBEDDING_PROVIDER (default: sentence-transformers).
    """

    def __init__(
        self,
        *,
        provider: str | None = None,
        model: str = "all-MiniLM-L6-v2",
        text_field: str = "text",
        output_property: str = "embedding",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"embedding:{provider or 'default'}")
        self._provider = provider
        self._model = model
        self._text_field = text_field
        self._output = output_property

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        import os

        body = exchange.in_message.body
        text = body.get(self._text_field) if isinstance(body, dict) else str(body)
        if not text:
            exchange.set_property(self._output, [])
            return

        provider = self._provider or os.environ.get(
            "EMBEDDING_PROVIDER", "sentence-transformers"
        )

        try:
            if provider == "openai":
                embedding = await self._openai_embed(text)
            elif provider == "ollama":
                embedding = await self._ollama_embed(text)
            else:
                embedding = await self._st_embed(text)
            exchange.set_property(self._output, embedding)
        except Exception as exc:
            exchange.fail(f"Embedding failed: {exc}")

    async def _st_embed(self, text: str) -> list[float]:
        from src.backend.services.ai.rag_service import get_rag_service

        rag = get_rag_service()
        if hasattr(rag, "_embed"):
            result = rag._embed(text)
            return result.tolist() if hasattr(result, "tolist") else list(result)
        raise RuntimeError("Sentence-transformers not available via RAG service")

    async def _openai_embed(self, text: str) -> list[float]:
        import os

        import httpx

        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not set")

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.openai.com/v1/embeddings",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"model": self._model, "input": text},
            )
            resp.raise_for_status()
            return resp.json()["data"][0]["embedding"]

    async def _ollama_embed(self, text: str) -> list[float]:
        import os

        import httpx

        base_url = os.environ.get("OLLAMA_URL", "http://localhost:11434")

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{base_url}/api/embeddings",
                json={"model": self._model, "prompt": text},
            )
            resp.raise_for_status()
            return resp.json()["embedding"]


class OutboxProcessor(BaseProcessor):
    """Transactional Outbox pattern — guaranteed delivery.

    Записывает сообщение в outbox-таблицу БД в той же транзакции,
    что и бизнес-данные. Фоновый relay читает outbox и публикует
    в брокер с гарантией exactly-once.

    Usage::
        .outbox(topic="orders.created", table_name="outbox_messages")

    Требует таблицу::
        CREATE TABLE outbox_messages (
            id UUID PRIMARY KEY,
            topic TEXT NOT NULL,
            payload JSONB NOT NULL,
            published_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT NOW()
        );
    """

    def __init__(
        self,
        *,
        topic: str,
        table_name: str = "outbox_messages",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"outbox:{topic}")
        self._topic = topic
        self._table = table_name

        # Validate table name (only allowlist — same as SEC-5 pattern)
        if not table_name.replace("_", "").isalnum():
            raise ValueError(f"Invalid outbox table name: {table_name}")

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        import uuid

        import orjson
        from sqlalchemy import text

        try:
            from src.backend.infrastructure.database.database import db_initializer
        except ImportError:
            exchange.fail("Database not configured for outbox")
            return

        body = exchange.in_message.body
        payload = body if isinstance(body, dict) else {"data": body}
        payload_json = orjson.dumps(payload, default=str).decode()
        msg_id = str(uuid.uuid4())

        try:
            engine = db_initializer.get_async_engine()
            async with engine.connect() as conn:
                await conn.execute(
                    text(f"""
                        INSERT INTO {self._table} (id, topic, payload)
                        VALUES (:id, :topic, CAST(:payload AS JSONB))
                    """),  # noqa: S608  # self._table провалидирован через .isalnum() в __init__
                    {"id": msg_id, "topic": self._topic, "payload": payload_json},
                )
                await conn.commit()

            exchange.set_property("outbox_message_id", msg_id)
            exchange.set_property("outbox_topic", self._topic)
        except Exception as exc:
            exchange.fail(f"Outbox insert failed: {exc}")
