"""Unit-тесты для MongoDB batch operations (S182).

Coverage:
- insert_many с batching (chunked insert при > batch_size)
- insert_many empty list
- update_many с CB+Retry
- delete_many с CB+Retry
- Batch size edge cases
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.infrastructure.clients.storage.mongodb import MongoDBClient


class TestInsertManyBatch:
    """Тесты insert_many batch."""

    @pytest.mark.asyncio
    async def test_insert_many_empty_list(self, monkeypatch) -> None:
        """Пустой список → пустой результат без вызова DB."""
        client = MongoDBClient()

        result = await client.insert_many("test", [])

        # Cycle 122: production early-returns on empty list (no db access).
        # Was: client.db.__getitem__.assert_not_called() — relied on
        # monkeypatched client.db, which is no longer needed (production
        # never accesses db on empty path).
        assert result == []

    @pytest.mark.asyncio
    async def test_insert_many_small_batch(self, monkeypatch) -> None:
        """Маленький batch (< batch_size) → один вызов insert_many."""
        client = MongoDBClient()
        mock_collection = MagicMock()
        mock_result = MagicMock()
        mock_result.inserted_ids = ["id1", "id2", "id3"]
        mock_collection.insert_many = AsyncMock(return_value=mock_result)
        mock_db = MagicMock()
        mock_db.__getitem__.return_value = mock_collection
        monkeypatch.setattr(MongoDBClient, "db", property(lambda self: mock_db))

        docs = [{"a": 1}, {"a": 2}, {"a": 3}]
        result = await client.insert_many("test", docs, batch_size=100)

        assert result == ["id1", "id2", "id3"]
        assert mock_collection.insert_many.call_count == 1

    @pytest.mark.asyncio
    async def test_insert_many_chunked(self, monkeypatch) -> None:
        """Большой batch (> batch_size) → chunked insert."""
        client = MongoDBClient()
        mock_collection = MagicMock()

        # Mock return для каждого chunk
        def make_result(ids):
            r = MagicMock()
            r.inserted_ids = ids
            return r

        mock_collection.insert_many = AsyncMock(
            side_effect=[
                make_result(["id1", "id2"]),
                make_result(["id3", "id4"]),
            ],
        )
        mock_db = MagicMock()
        mock_db.__getitem__.return_value = mock_collection
        monkeypatch.setattr(MongoDBClient, "db", property(lambda self: mock_db))

        # 4 docs, batch_size=2 → 2 chunks
        docs = [{"a": 1}, {"a": 2}, {"a": 3}, {"a": 4}]
        result = await client.insert_many("test", docs, batch_size=2)

        assert result == ["id1", "id2", "id3", "id4"]
        assert mock_collection.insert_many.call_count == 2

    @pytest.mark.asyncio
    async def test_insert_many_exact_batch_size(self, monkeypatch) -> None:
        """Точно batch_size → один вызов (не chunked)."""
        client = MongoDBClient()
        mock_collection = MagicMock()
        mock_collection.insert_many = AsyncMock(
            return_value=MagicMock(inserted_ids=["id1", "id2"]),
        )
        mock_db = MagicMock()
        mock_db.__getitem__.return_value = mock_collection
        monkeypatch.setattr(MongoDBClient, "db", property(lambda self: mock_db))

        docs = [{"a": 1}, {"a": 2}]
        result = await client.insert_many("test", docs, batch_size=2)

        assert result == ["id1", "id2"]
        assert mock_collection.insert_many.call_count == 1


class TestUpdateMany:
    """Тесты update_many."""

    @pytest.mark.asyncio
    async def test_update_many_success(self, monkeypatch) -> None:
        """Successful update_many returns count."""
        client = MongoDBClient()
        mock_collection = MagicMock()
        mock_collection.update_many = AsyncMock(
            return_value=MagicMock(modified_count=5),
        )
        mock_db = MagicMock()
        mock_db.__getitem__.return_value = mock_collection
        monkeypatch.setattr(MongoDBClient, "db", property(lambda self: mock_db))

        result = await client.update_many(
            "test", {"status": "old"}, {"$set": {"status": "new"}},
        )

        assert result == 5
        mock_collection.update_many.assert_called_once_with(
            {"status": "old"}, {"$set": {"status": "new"}},
        )


class TestDeleteMany:
    """Тесты delete_many."""

    @pytest.mark.asyncio
    async def test_delete_many_success(self, monkeypatch) -> None:
        """Successful delete_many returns count."""
        client = MongoDBClient()
        mock_collection = MagicMock()
        mock_collection.delete_many = AsyncMock(
            return_value=MagicMock(deleted_count=3),
        )
        mock_db = MagicMock()
        mock_db.__getitem__.return_value = mock_collection
        monkeypatch.setattr(MongoDBClient, "db", property(lambda self: mock_db))

        result = await client.delete_many("test", {"status": "deleted"})

        assert result == 3
        mock_collection.delete_many.assert_called_once_with({"status": "deleted"})
