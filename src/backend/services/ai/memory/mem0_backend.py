"""Mem0 memory backend — implements MemoryProtocol (W10 GAP-AI, S35 W1).

Wraps ``mem0ai`` SDK as a :class:`MemoryProtocol` backend.

Namespace convention: ``"<tenant_id>:<scope>"`` → mem0ai ``user_id``.
Example: ``"acme:credit_chat"`` → mem0ai ``user_id="acme:credit_chat"``

Usage::

    from src.backend.services.ai.memory.mem0_backend import Mem0MemoryAdapter

    backend = Mem0MemoryAdapter()
    await backend.store("acme:chat", "user_prefs", {"pref": "dark_mode"})
    records = await backend.recall("acme:chat", "dark mode preferences", k=5)

Feature-flag: ``feature_flags.mem0ai_enabled`` (default-OFF).
"""

from __future__ import annotations

from typing import Any

from src.backend.infrastructure.logging.factory import get_logger

__all__ = ("Mem0MemoryAdapter",)

logger = get_logger(__name__)


class Mem0BackendUnavailableError(Exception):
    """Raised when mem0ai extra is not installed or backend is disabled."""


class Mem0MemoryAdapter:
    """Mem0-backed :class:`MemoryProtocol` implementation.

    Implements recall/store/delete via mem0ai SDK.
    Gracefully falls back to no-op when ``mem0ai`` is not installed
    or ``feature_flags.mem0ai_enabled=False``.

    Args:
        fail_open: Если True (default) — при ошибках возвращает пустой
            результат вместо поднятия исключения.
    """

    def __init__(self, fail_open: bool = True) -> None:
        self._fail_open = fail_open
        self._client: Any | None = None
        self._initialized = False

    # ── MemoryProtocol ────────────────────────────────────────────────────────

    async def recall(
        self, namespace: str, query: str, *, k: int = 5
    ) -> list[dict[str, Any]]:
        """Search semantic memories matching ``query``.

        Maps to ``mem0ai.Memory.search(query, user_id=namespace)``.
        """
        client = await self._get_client()
        if client is None:
            return []

        try:
            results = client.search(query=query, user_id=namespace, top_k=k)
            return self._normalize_results(results)
        except Exception as exc:
            logger.warning(
                "Mem0MemoryAdapter.recall(%r, %r) failed: %s", namespace, query, exc
            )
            if self._fail_open:
                return []
            raise

    async def store(
        self, namespace: str, key: str, value: Any, *, ttl_s: int | None = None
    ) -> None:
        """Store a memory record.

        Maps to ``mem0ai.Memory.add(message, user_id=namespace)``.
        ``key`` is stored in metadata for idempotent deduplication.
        ``ttl_s`` is not directly supported by mem0ai — logged and ignored.
        """
        client = await self._get_client()
        if client is None:
            return

        text = self._serialize_value(key, value)
        metadata = {"mem0_key": key}
        if ttl_s is not None:
            metadata["ttl_s"] = ttl_s

        try:
            client.add(
                messages=[{"role": "user", "content": text}],
                user_id=namespace,
                metadata=metadata,
            )
        except Exception as exc:
            logger.warning(
                "Mem0MemoryAdapter.store(%r, %r) failed: %s", namespace, key, exc
            )
            if not self._fail_open:
                raise

    async def delete(self, namespace: str, key: str) -> None:
        """Delete memory record by key (idempotent).

        Implementation: searches for records with ``mem0_key=key`` and
        deletes them. Note: mem0ai API does not have direct delete by key,
        so this performs a search + delete of matching records.
        """
        client = await self._get_client()
        if client is None:
            return

        try:
            results = client.search(query=key, user_id=namespace, top_k=100)
            for record in results.get("results", []):
                mem_id = record.get("memory_id") or record.get("id")
                record_key = (
                    record.get("metadata", {}).get("mem0_key", "")
                    if isinstance(record.get("metadata"), dict)
                    else ""
                )
                if mem_id and record_key == key:
                    try:
                        client.delete(memory_id=mem_id)
                    except Exception as exc:
                        logger.debug(
                            "Mem0MemoryAdapter.delete memory_id=%s failed: %s",
                            mem_id,
                            exc,
                        )
        except Exception as exc:
            logger.warning(
                "Mem0MemoryAdapter.delete(%r, %r) failed: %s", namespace, key, exc
            )
            if not self._fail_open:
                raise

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _get_client(self) -> Any | None:
        """Lazily initialize mem0ai client."""
        if not self._initialized:
            self._initialized = True
            if not self._is_enabled():
                return None
            self._client = self._create_client()
        return self._client

    def _is_enabled(self) -> bool:
        """Check feature-flag mem0ai_enabled."""
        try:
            from src.backend.core.config.features import feature_flags

            return bool(feature_flags.mem0ai_enabled)
        except Exception:
            return False

    def _create_client(self) -> Any | None:
        """Create mem0ai Memory client with lazy import."""
        try:
            from mem0 import Memory
        except ImportError:
            logger.debug(
                "mem0ai not installed — Mem0MemoryAdapter unavailable. "
                "Install with: pip install 'gd-integration-tools[ai-memory]'"
            )
            return None

        try:
            return Memory()
        except Exception as exc:
            logger.warning("Mem0MemoryAdapter: Memory() init failed: %s", exc)
            return None

    @staticmethod
    def _serialize_value(key: str, value: Any) -> str:
        """Serialize key+value to text for mem0ai storage."""
        import json

        if isinstance(value, str):
            text_value = value
        else:
            try:
                text_value = json.dumps(value, ensure_ascii=False, default=str)
            except Exception:
                text_value = str(value)

        return f"[{key}] {text_value}"

    @staticmethod
    def _normalize_results(results: Any) -> list[dict[str, Any]]:
        """Normalize mem0ai search results to MemoryRecord list."""
        records: list[dict[str, Any]] = []

        # Handle both dict and non-dict responses
        if results is None:
            return records

        if isinstance(results, dict):
            raw_results = results.get("results", results.get("memories", []))
        else:
            raw_results = results if isinstance(results, list) else []

        for item in raw_results:
            if not isinstance(item, dict):
                continue
            mem_id = item.get("memory_id") or item.get("id", "")
            records.append(
                {
                    "key": item.get("metadata", {}).get("mem0_key", ""),
                    "value": item.get("content", ""),
                    "score": float(item.get("score", 0.0) or 0.0),
                    "metadata": {
                        "memory_id": mem_id,
                        "created_at": item.get("created_at"),
                    },
                }
            )

        return records
