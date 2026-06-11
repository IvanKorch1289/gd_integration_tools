from __future__ import annotations

"""S67 W3 - l3_cache.py part of semantic_cache decomp.

Per-class file split.

Classes: L3RetrievalGraphCache.
"""

import asyncio
import contextlib
import hashlib
import time
from typing import Any

#: Redis pub/sub канал для cross-instance invalidation L3-кеша.
RAG_CACHE_INVALIDATE_CHANNEL = "rag-cache-invalidate"


class L3RetrievalGraphCache:
    """In-process cache RAG retrieval-result с pub/sub invalidation.

    Слой L3 поверх семантического (L2) и exact (L1):
    - Хранит kortej (namespace, query_hash) → list[doc_dict].
    - Cross-instance invalidation: подписка на Redis channel
      :data:`RAG_CACHE_INVALIDATE_CHANNEL`. Сообщение
      ``{"namespace": "<ns>", "doc_id": "<id>"}`` сбрасывает все
      записи указанного namespace; ``{"namespace": "*"}`` — полностью.
    - Активация: ``feature_flags.rag_cache_l3_retrieval_invalidation``.
      При выключенном флаге методы возвращают None / no-op (нулевой overhead).

    Используется как opt-in fast-path в RAG-pipeline:
        cache = get_l3_retrieval_cache()
        hit = await cache.lookup(query, namespace=ns)
        if hit is not None:
            return hit
        result = await rag.search(query=query, namespace=ns, top_k=k)
        await cache.store(query, namespace=ns, result=result)
    """

    def __init__(self, *, max_entries: int = 4096, ttl_seconds: int = 600) -> None:
        """Инициализирует in-process L3 store.

        Args:
            max_entries: Жёсткий лимит записей; при превышении применяется
                FIFO-вытеснение по времени вставки.
            ttl_seconds: TTL записи в секундах; expired-записи удаляются
                lazy при lookup.
        """
        self._max_entries = max_entries
        self._ttl = ttl_seconds
        self._store: dict[str, dict[str, Any]] = {}
        self._invalidation_task: asyncio.Task[None] | None = None

    # ─── lifecycle ────────────────────────────────────────────────────────

    def _is_enabled(self) -> bool:
        """True при включённом feature_flags.rag_cache_l3_retrieval_invalidation."""
        try:
            from src.backend.core.config.features import feature_flags

            return bool(
                getattr(feature_flags, "rag_cache_l3_retrieval_invalidation", False)
            )
        except Exception as _:
            return False

    @staticmethod
    def _key(query: str, namespace: str | None) -> str:
        """SHA-256 hash от пары (namespace, query)."""
        ns = namespace or "default"
        raw = f"{ns}::{query}".encode()
        return hashlib.sha256(raw).hexdigest()

    # ─── core API ─────────────────────────────────────────────────────────

    async def lookup(
        self, query: str, *, namespace: str | None = None
    ) -> list[dict[str, Any]] | None:
        """Возвращает кешированный retrieval-result или None.

        Args:
            query: Текст запроса.
            namespace: RAG-коллекция / namespace.

        Returns:
            Список документов либо None, если запись отсутствует, истекла
            либо feature-flag выключен.
        """
        if not self._is_enabled():
            return None
        key = self._key(query, namespace)
        record = self._store.get(key)
        if record is None:
            return None
        if time.time() - record["stored_at"] > self._ttl:
            self._store.pop(key, None)
            return None
        return list(record["result"])

    async def store(
        self, query: str, *, namespace: str | None, result: list[dict[str, Any]]
    ) -> None:
        """Сохраняет retrieval-result для (query, namespace).

        Args:
            query: Текст запроса.
            namespace: RAG-коллекция / namespace.
            result: Список документов из RAG-поиска.
        """
        if not self._is_enabled():
            return
        if len(self._store) >= self._max_entries:
            # FIFO-вытеснение самой старой записи
            oldest_key = min(self._store, key=lambda k: self._store[k]["stored_at"])
            self._store.pop(oldest_key, None)
        self._store[self._key(query, namespace)] = {
            "namespace": namespace or "default",
            "result": list(result),
            "stored_at": time.time(),
        }

    # ─── invalidation API ────────────────────────────────────────────────

    def invalidate_namespace(self, namespace: str) -> int:
        """Удаляет все записи указанного namespace ("*" — все).

        Args:
            namespace: Имя namespace или "*" для полного flush.

        Returns:
            Количество удалённых записей.
        """
        if namespace == "*":
            removed = len(self._store)
            self._store.clear()
            return removed
        keys = [
            k for k, rec in self._store.items() if rec.get("namespace") == namespace
        ]
        for k in keys:
            self._store.pop(k, None)
        return len(keys)

    async def publish_invalidate(
        self, namespace: str, *, doc_id: str | None = None
    ) -> bool:
        """Публикует invalidation-сообщение в Redis pub/sub.

        Args:
            namespace: Намespace для инвалидации ("*" — все).
            doc_id: Опциональный идентификатор документа (информационно).

        Returns:
            True при успешной публикации, False при недоступности Redis.
        """
        if not self._is_enabled():
            return False
        try:
            import orjson

            from src.backend.core.di.providers import get_redis_stream_client_provider

            redis_client = get_redis_stream_client_provider()
        except Exception as _:
            return False
        payload = orjson.dumps({"namespace": namespace, "doc_id": doc_id})
        try:
            raw = getattr(redis_client, "_raw_client", None) or redis_client
            await raw.publish(RAG_CACHE_INVALIDATE_CHANNEL, payload)
            return True
        except Exception as exc:
            logger.debug("L3 invalidate publish failed: %s", exc)
            return False

    async def start_invalidation_listener(self) -> None:
        """Запускает background-задачу подписки на Redis pub/sub.

        Безопасно при повторных вызовах — единственный listener на инстанс.
        Гасится через :meth:`stop_invalidation_listener`.
        """
        if self._invalidation_task is not None and not self._invalidation_task.done():
            return
        if not self._is_enabled():
            return
        from src.backend.core.utils.task_registry import get_task_registry

        self._invalidation_task = get_task_registry().create_task(
            self._listen_loop(), name="l3-rag-cache-invalidate"
        )

    async def stop_invalidation_listener(self) -> None:
        """Останавливает background pub/sub listener."""
        if self._invalidation_task is None:
            return
        self._invalidation_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await self._invalidation_task
        self._invalidation_task = None

    async def _listen_loop(self) -> None:
        """Подписка на Redis-канал и применение invalidation-сообщений."""
        try:
            import orjson

            from src.backend.core.di.providers import get_redis_pubsub_factory_provider

            factory = get_redis_pubsub_factory_provider()
            if factory is None:
                logger.debug("L3 listener: redis pubsub factory unavailable")
                return
            pubsub = factory() if callable(factory) else factory
            await pubsub.subscribe(RAG_CACHE_INVALIDATE_CHANNEL)
        except Exception as exc:
            logger.debug("L3 listener startup failed: %s", exc)
            return
        try:
            async for message in pubsub.listen():
                if not isinstance(message, dict) or message.get("type") != "message":
                    continue
                try:
                    payload = orjson.loads(message.get("data") or b"{}")
                except Exception as _:
                    continue
                ns = payload.get("namespace") or "*"
                self.invalidate_namespace(ns)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.debug("L3 listener loop error: %s", exc)
