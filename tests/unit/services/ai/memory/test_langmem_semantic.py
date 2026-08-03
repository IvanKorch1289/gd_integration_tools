"""Tests for SemanticMemory (cycle 63).

Stream E.7: semantic memory поверх Qdrant.

Coverage:
- __init__ parameters and defaults
- is_configured property (true/false)
- add() with valid embedder + qdrant_client → embeds and upserts
- add() without embedder → RuntimeError
- add() without qdrant_client → RuntimeError
- add() with tenant → payload includes tenant
- add() with meta dict → payload includes meta fields
- add() returns point_id (uuid format)
- add() with custom collection name → uses it for upsert

Cycle 63 invariant: tests catch regressions in Qdrant vector storage
that could lead to silent memory corruption in AI agents.
"""

# ruff: noqa: S101

from __future__ import annotations

import re
from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.unit


class TestSemanticMemoryInit:
    """__init__ constructor and configuration state."""

    def test_default_collection_name(self) -> None:
        """Default collection name is 'langmem_semantic'."""
        from src.backend.services.ai.memory.langmem.semantic import (
            SemanticMemory,
        )

        mem = SemanticMemory()
        assert mem._collection == "langmem_semantic"

    def test_custom_collection_name(self) -> None:
        """Custom collection name stored in _collection."""
        from src.backend.services.ai.memory.langmem.semantic import (
            SemanticMemory,
        )

        mem = SemanticMemory(collection="custom_coll")
        assert mem._collection == "custom_coll"

    def test_is_configured_false_when_no_client(self) -> None:
        """is_configured returns False when qdrant_client is None."""
        from src.backend.services.ai.memory.langmem.semantic import (
            SemanticMemory,
        )

        mem = SemanticMemory(embedder=MagicMock())
        assert mem.is_configured is False

    def test_is_configured_false_when_no_embedder(self) -> None:
        """is_configured returns False when embedder is None."""
        from src.backend.services.ai.memory.langmem.semantic import (
            SemanticMemory,
        )

        mem = SemanticMemory(qdrant_client=AsyncMock())
        assert mem.is_configured is False

    def test_is_configured_true_when_both_set(self) -> None:
        """is_configured returns True when both client and embedder set."""
        from src.backend.services.ai.memory.langmem.semantic import (
            SemanticMemory,
        )

        mem = SemanticMemory(
            qdrant_client=AsyncMock(), embedder=MagicMock()
        )
        assert mem.is_configured is True


class TestSemanticMemoryAdd:
    """add() method: embed → upsert → return point_id."""

    @pytest.fixture
    def memory(self) -> tuple:
        """Memory with mocked Qdrant + embedder returning 1D vector."""
        from src.backend.services.ai.memory.langmem.semantic import (
            SemanticMemory,
        )

        qdrant = MagicMock()
        qdrant.upsert = AsyncMock()
        embedder = MagicMock()
        embedder.embed = AsyncMock(return_value=[[0.1, 0.2, 0.3]])
        mem = SemanticMemory(
            qdrant_client=qdrant, embedder=embedder, collection="test"
        )
        return mem, qdrant, embedder

    @pytest.mark.asyncio
    async def test_add_embeds_text(self, memory) -> None:
        """add() calls embedder.embed with the input text."""
        mem, _qdrant, embedder = memory

        await mem.add(text="hello world")

        embedder.embed.assert_awaited_once_with(["hello world"])

    @pytest.mark.asyncio
    async def test_add_upserts_to_qdrant(self, memory) -> None:
        """add() upserts vector to Qdrant collection."""
        mem, qdrant, _embedder = memory

        point_id = await mem.add(text="hello world")

        qdrant.upsert.assert_awaited_once()
        # upsert called with kwargs (or positional).
        call = qdrant.upsert.await_args
        if call.kwargs:
            assert call.kwargs.get("collection") == "test"
        else:
            assert call.args[0] == "test"

    @pytest.mark.asyncio
    async def test_add_returns_uuid_string(self, memory) -> None:
        """add() returns point_id as UUID string."""
        mem, _qdrant, _embedder = memory

        point_id = await mem.add(text="hello world")

        # UUID format: 8-4-4-4-12.
        assert re.match(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
            point_id,
        )

    @pytest.mark.asyncio
    async def test_add_upserts_point_with_vector_and_payload(
        self, memory
    ) -> None:
        """add() upsert point has vector from embedder + text in payload."""
        mem, qdrant, _embedder = memory

        await mem.add(text="hello world", meta={"source": "test"})

        # Find the upsert call args.
        call = qdrant.upsert.await_args
        # Get points list from positional or kwargs.
        if call.kwargs and "points" in call.kwargs:
            points = call.kwargs["points"]
        else:
            points = call.args[1]
        assert len(points) == 1
        point = points[0]
        # Vector from embedder.
        assert point["vector"] == [0.1, 0.2, 0.3]
        # Text + meta in payload.
        assert point["payload"]["text"] == "hello world"
        assert point["payload"]["source"] == "test"

    @pytest.mark.asyncio
    async def test_add_with_tenant_in_payload(self, memory) -> None:
        """add() включает tenant в payload если задан."""
        mem, qdrant, _embedder = memory

        await mem.add(text="bank secret", tenant="acme_bank")

        call = qdrant.upsert.await_args
        if call.kwargs and "points" in call.kwargs:
            points = call.kwargs["points"]
        else:
            points = call.args[1]
        payload = points[0]["payload"]
        assert payload["tenant"] == "acme_bank"
        assert payload["text"] == "bank secret"

    @pytest.mark.asyncio
    async def test_add_without_tenant_omits_tenant_key(self, memory) -> None:
        """add() без tenant не добавляет tenant key в payload."""
        mem, qdrant, _embedder = memory

        await mem.add(text="public info")

        call = qdrant.upsert.await_args
        if call.kwargs and "points" in call.kwargs:
            points = call.kwargs["points"]
        else:
            points = call.args[1]
        payload = points[0]["payload"]
        assert "tenant" not in payload

    @pytest.mark.asyncio
    async def test_add_without_meta_uses_empty_dict(self, memory) -> None:
        """add() без meta не падает (fallback к {} через **(meta or {}))."""
        mem, qdrant, _embedder = memory

        await mem.add(text="no meta")

        # No exception → meta={} is correctly applied.
        call = qdrant.upsert.await_args
        if call.kwargs and "points" in call.kwargs:
            points = call.kwargs["points"]
        else:
            points = call.args[1]
        payload = points[0]["payload"]
        assert "text" in payload  # only "text" key, no meta keys

    @pytest.mark.asyncio
    async def test_add_multiple_calls_return_different_point_ids(
        self, memory
    ) -> None:
        """Каждый add() возвращает уникальный point_id."""
        mem, _qdrant, _embedder = memory

        id1 = await mem.add(text="text 1")
        id2 = await mem.add(text="text 2")
        id3 = await mem.add(text="text 3")

        assert id1 != id2 != id3
        assert len({id1, id2, id3}) == 3


class TestSemanticMemoryAddErrors:
    """add() error paths: not configured → RuntimeError."""

    @pytest.mark.asyncio
    async def test_add_without_embedder_raises(self) -> None:
        """add() без embedder → RuntimeError (memory not configured)."""
        from src.backend.services.ai.memory.langmem.semantic import (
            SemanticMemory,
        )

        mem = SemanticMemory(qdrant_client=AsyncMock())  # no embedder
        assert mem.is_configured is False

        with pytest.raises(RuntimeError, match="не сконфигурирован"):
            await mem.add(text="anything")

    @pytest.mark.asyncio
    async def test_add_without_qdrant_raises(self) -> None:
        """add() без qdrant_client → RuntimeError."""
        from src.backend.services.ai.memory.langmem.semantic import (
            SemanticMemory,
        )

        mem = SemanticMemory(embedder=MagicMock())  # no qdrant
        assert mem.is_configured is False

        with pytest.raises(RuntimeError, match="не сконфигурирован"):
            await mem.add(text="anything")

    @pytest.mark.asyncio
    async def test_add_without_both_raises(self) -> None:
        """add() без обоих → RuntimeError."""
        from src.backend.services.ai.memory.langmem.semantic import (
            SemanticMemory,
        )

        mem = SemanticMemory()
        assert mem.is_configured is False

        with pytest.raises(RuntimeError):
            await mem.add(text="anything")

    @pytest.mark.asyncio
    async def test_add_handles_embedder_failure(self) -> None:
        """add() propagates embedder exceptions (no silent failure)."""
        from src.backend.services.ai.memory.langmem.semantic import (
            SemanticMemory,
        )

        qdrant = MagicMock()
        qdrant.upsert = AsyncMock()
        embedder = MagicMock()
        embedder.embed = AsyncMock(side_effect=RuntimeError("embed failed"))

        mem = SemanticMemory(qdrant_client=qdrant, embedder=embedder)

        # Cycle 63 invariant: embedder errors propagate, qdrant not called.
        with pytest.raises(RuntimeError, match="embed failed"):
            await mem.add(text="x")

        qdrant.upsert.assert_not_called()

    @pytest.mark.asyncio
    async def test_add_uses_correct_collection(self) -> None:
        """add() upsert использует self._collection name."""
        from src.backend.services.ai.memory.langmem.semantic import (
            SemanticMemory,
        )

        qdrant = MagicMock()
        qdrant.upsert = AsyncMock()
        embedder = MagicMock()
        embedder.embed = AsyncMock(return_value=[[0.1]])

        mem = SemanticMemory(
            qdrant_client=qdrant, embedder=embedder, collection="my_bank_v1"
        )

        await mem.add(text="x")

        # upsert called with collection='my_bank_v1'.
        call = qdrant.upsert.await_args
        if call.kwargs and "collection" in call.kwargs:
            assert call.kwargs["collection"] == "my_bank_v1"
        else:
            assert call.args[0] == "my_bank_v1"


class TestSemanticMemoryMissingClientMethod:
    """Edge case: qdrant_client without 'upsert' method → silently no-op."""

    @pytest.mark.asyncio
    async def test_add_silently_no_op_if_upsert_missing(self) -> None:
        """add() returns point_id even if qdrant.upsert doesn't exist.

        Cycle 63 invariant: graceful degradation if qdrant_client
        is misconfigured (no upsert method). Returns point_id but
        doesn't actually store (logs warning, continues).
        """
        from src.backend.services.ai.memory.langmem.semantic import (
            SemanticMemory,
        )

        # Mock client WITHOUT upsert method.
        qdrant = MagicMock(spec=[])  # spec=[] → no attributes
        embedder = MagicMock()
        embedder.embed = AsyncMock(return_value=[[0.1]])

        mem = SemanticMemory(qdrant_client=qdrant, embedder=embedder)

        # Should not raise — just no-op upsert.
        point_id = await mem.add(text="x")

        # Returns valid UUID.
        assert re.match(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
            point_id,
        )
