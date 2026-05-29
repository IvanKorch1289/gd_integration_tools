"""Unit tests for Mem0MemoryAdapter (W10 GAP-AI, S35 W1).

Tests mock mem0ai import to avoid requiring the extra in dev_light.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ── Recall ────────────────────────────────────────────────────────────────────


class TestMem0MemoryAdapterRecall:
    """Test recall() with mocked mem0ai."""

    @pytest.mark.asyncio
    async def test_recall_returns_normalized_records(self):
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "results": [
                {
                    "content": "User prefers dark mode",
                    "score": 0.95,
                    "memory_id": "mem-1",
                    "created_at": "2026-01-01T00:00:00Z",
                    "metadata": {"mem0_key": "pref_dark_mode"},
                },
            ]
        }

        with patch.dict("sys.modules", {"mem0": MagicMock()}):
            from src.backend.services.ai.memory.mem0_backend import Mem0MemoryAdapter

            adapter = Mem0MemoryAdapter()
            adapter._client = mock_client
            adapter._initialized = True

            results = await adapter.recall("acme:chat", "dark mode", k=5)

        assert len(results) == 1
        assert results[0]["key"] == "pref_dark_mode"
        assert results[0]["value"] == "User prefers dark mode"
        assert results[0]["score"] == 0.95
        mock_client.search.assert_called_once_with(
            query="dark mode", user_id="acme:chat", top_k=5
        )

    @pytest.mark.asyncio
    async def test_recall_empty_when_client_none(self):
        with patch.dict("sys.modules", {"mem0": MagicMock()}):
            from src.backend.services.ai.memory.mem0_backend import Mem0MemoryAdapter

            adapter = Mem0MemoryAdapter()
            adapter._client = None
            adapter._initialized = True

            results = await adapter.recall("acme:chat", "query", k=3)

        assert results == []

    @pytest.mark.asyncio
    async def test_recall_fail_open_returns_empty(self):
        mock_client = MagicMock()
        mock_client.search.side_effect = RuntimeError("connection failed")

        with patch.dict("sys.modules", {"mem0": MagicMock()}):
            from src.backend.services.ai.memory.mem0_backend import Mem0MemoryAdapter

            adapter = Mem0MemoryAdapter(fail_open=True)
            adapter._client = mock_client
            adapter._initialized = True

            results = await adapter.recall("acme:chat", "query")

        assert results == []

    @pytest.mark.asyncio
    async def test_recall_fail_closed_raises(self):
        mock_client = MagicMock()
        mock_client.search.side_effect = RuntimeError("connection failed")

        with patch.dict("sys.modules", {"mem0": MagicMock()}):
            from src.backend.services.ai.memory.mem0_backend import Mem0MemoryAdapter

            adapter = Mem0MemoryAdapter(fail_open=False)
            adapter._client = mock_client
            adapter._initialized = True

            with pytest.raises(RuntimeError, match="connection failed"):
                await adapter.recall("acme:chat", "query")


# ── Store ─────────────────────────────────────────────────────────────────────


class TestMem0MemoryAdapterStore:
    """Test store() with mocked mem0ai."""

    @pytest.mark.asyncio
    async def test_store_calls_mem0_add(self):
        mock_client = MagicMock()

        with patch.dict("sys.modules", {"mem0": MagicMock()}):
            from src.backend.services.ai.memory.mem0_backend import Mem0MemoryAdapter

            adapter = Mem0MemoryAdapter()
            adapter._client = mock_client
            adapter._initialized = True

            await adapter.store(
                "acme:chat",
                "user_pref",
                {"theme": "dark", "lang": "ru"},
            )

        mock_client.add.assert_called_once()
        call_kwargs = mock_client.add.call_args.kwargs
        assert call_kwargs["user_id"] == "acme:chat"
        assert "[user_pref]" in call_kwargs["messages"][0]["content"]
        assert call_kwargs["metadata"]["mem0_key"] == "user_pref"

    @pytest.mark.asyncio
    async def test_store_noop_when_client_none(self):
        with patch.dict("sys.modules", {"mem0": MagicMock()}):
            from src.backend.services.ai.memory.mem0_backend import Mem0MemoryAdapter

            adapter = Mem0MemoryAdapter()
            adapter._client = None
            adapter._initialized = True

            # Should not raise
            await adapter.store("acme:chat", "key", "value")

    @pytest.mark.asyncio
    async def test_store_string_value(self):
        mock_client = MagicMock()

        with patch.dict("sys.modules", {"mem0": MagicMock()}):
            from src.backend.services.ai.memory.mem0_backend import Mem0MemoryAdapter

            adapter = Mem0MemoryAdapter()
            adapter._client = mock_client
            adapter._initialized = True

            await adapter.store("acme:chat", "note", "hello world")

        call_kwargs = mock_client.add.call_args.kwargs
        assert "hello world" in call_kwargs["messages"][0]["content"]


# ── Delete ────────────────────────────────────────────────────────────────────


class TestMem0MemoryAdapterDelete:
    """Test delete() with mocked mem0ai."""

    @pytest.mark.asyncio
    async def test_delete_searches_and_deletes(self):
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "results": [
                {
                    "id": "mem-1",
                    "content": "old value",
                    "metadata": {"mem0_key": "old_key"},
                },
                {
                    "id": "mem-2",
                    "content": "other",
                    "metadata": {"mem0_key": "other_key"},
                },
            ]
        }

        with patch.dict("sys.modules", {"mem0": MagicMock()}):
            from src.backend.services.ai.memory.mem0_backend import Mem0MemoryAdapter

            adapter = Mem0MemoryAdapter()
            adapter._client = mock_client
            adapter._initialized = True

            await adapter.delete("acme:chat", "old_key")

        mock_client.delete.assert_called_once_with(memory_id="mem-1")

    @pytest.mark.asyncio
    async def test_delete_idempotent_when_not_found(self):
        mock_client = MagicMock()
        mock_client.search.return_value = {"results": []}

        with patch.dict("sys.modules", {"mem0": MagicMock()}):
            from src.backend.services.ai.memory.mem0_backend import Mem0MemoryAdapter

            adapter = Mem0MemoryAdapter()
            adapter._client = mock_client
            adapter._initialized = True

            await adapter.delete("acme:chat", "nonexistent")

        mock_client.delete.assert_not_called()


# ── Normalize ────────────────────────────────────────────────────────────────


class TestMem0MemoryAdapterNormalizeResults:
    """Test _normalize_results."""

    def test_normalize_dict_response(self):
        with patch.dict("sys.modules", {"mem0": MagicMock()}):
            from src.backend.services.ai.memory.mem0_backend import Mem0MemoryAdapter

            raw = [
                {
                    "content": "Memory content",
                    "score": 0.8,
                    "id": "mem-5",
                    "created_at": "2026-01-01T00:00:00Z",
                    "metadata": {"mem0_key": "test_key"},
                }
            ]
            records = Mem0MemoryAdapter._normalize_results(raw)

        assert len(records) == 1
        assert records[0]["key"] == "test_key"
        assert records[0]["value"] == "Memory content"
        assert records[0]["score"] == 0.8
        assert records[0]["metadata"]["memory_id"] == "mem-5"

    def test_normalize_empty_response(self):
        with patch.dict("sys.modules", {"mem0": MagicMock()}):
            from src.backend.services.ai.memory.mem0_backend import Mem0MemoryAdapter

            assert Mem0MemoryAdapter._normalize_results([]) == []
            assert Mem0MemoryAdapter._normalize_results(None) == []

    def test_normalize_none_scores(self):
        with patch.dict("sys.modules", {"mem0": MagicMock()}):
            from src.backend.services.ai.memory.mem0_backend import Mem0MemoryAdapter

            raw = [{"content": "test", "score": None, "id": "m1", "metadata": {}}]
            records = Mem0MemoryAdapter._normalize_results(raw)

        assert records[0]["score"] == 0.0


# ── Serialize ─────────────────────────────────────────────────────────────────


class TestMem0MemoryAdapterSerializeValue:
    """Test _serialize_value."""

    def test_serialize_dict(self):
        with patch.dict("sys.modules", {"mem0": MagicMock()}):
            from src.backend.services.ai.memory.mem0_backend import Mem0MemoryAdapter

            text = Mem0MemoryAdapter._serialize_value(
                "user_prefs", {"theme": "dark", "count": 42}
            )

        assert "[user_prefs]" in text
        assert "dark" in text
        assert "42" in text

    def test_serialize_string(self):
        with patch.dict("sys.modules", {"mem0": MagicMock()}):
            from src.backend.services.ai.memory.mem0_backend import Mem0MemoryAdapter

            text = Mem0MemoryAdapter._serialize_value("note", "hello world")

        assert text == "[note] hello world"

    def test_serialize_numeric(self):
        with patch.dict("sys.modules", {"mem0": MagicMock()}):
            from src.backend.services.ai.memory.mem0_backend import Mem0MemoryAdapter

            text = Mem0MemoryAdapter._serialize_value("score", 99.5)

        assert "[score]" in text
        assert "99.5" in text
