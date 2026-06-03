"""Unit tests for src.backend.core.interfaces.vector_store."""

from __future__ import annotations

import pytest

from src.backend.core.interfaces.vector_store import BaseVectorStore


class TestBaseVectorStore:
    def test_cannot_instantiate(self) -> None:
        with pytest.raises(TypeError):
            BaseVectorStore()  # type: ignore[abstract]

    def test_partial_subclass_fails(self) -> None:
        class Partial(BaseVectorStore):
            async def upsert(
                self,
                embeddings: list[list[float]],
                documents: list[str],
                ids: list[str],
                metadatas: list[dict[str, object]] | None = None,
            ) -> None:
                pass

        with pytest.raises(TypeError):
            Partial()  # type: ignore[abstract]

    def test_valid_subclass(self) -> None:
        class Full(BaseVectorStore):
            async def upsert(
                self,
                embeddings: list[list[float]],
                documents: list[str],
                ids: list[str],
                metadatas: list[dict[str, object]] | None = None,
            ) -> None:
                pass

            async def query(
                self,
                embedding: list[float],
                top_k: int = 5,
                where: dict[str, object] | None = None,
            ) -> list[dict[str, object]]:
                return []

            async def delete(self, ids: list[str]) -> None:
                pass

            async def count(self) -> int:
                return 0

        inst = Full()
        assert inst is not None

    @pytest.mark.asyncio
    async def test_default_methods_raise(self) -> None:
        class Full(BaseVectorStore):
            async def upsert(
                self,
                embeddings: list[list[float]],
                documents: list[str],
                ids: list[str],
                metadatas: list[dict[str, object]] | None = None,
            ) -> None:
                pass

            async def query(
                self,
                embedding: list[float],
                top_k: int = 5,
                where: dict[str, object] | None = None,
            ) -> list[dict[str, object]]:
                return []

            async def delete(self, ids: list[str]) -> None:
                pass

            async def count(self) -> int:
                return 0

        inst = Full()
        with pytest.raises(NotImplementedError):
            await inst.delete_where({"k": "v"})
        with pytest.raises(NotImplementedError):
            await inst.count_where({"k": "v"})
