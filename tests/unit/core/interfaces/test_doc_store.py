"""Unit tests for src.backend.core.interfaces.doc_store."""

from __future__ import annotations

import pytest

from src.backend.core.interfaces.doc_store import DocStoreBackend


class TestDocStoreBackend:
    def test_cannot_instantiate(self) -> None:
        with pytest.raises(TypeError):
            DocStoreBackend()  # type: ignore[abstract]

    def test_partial_subclass_fails(self) -> None:
        class Partial(DocStoreBackend):
            async def insert(
                self,
                namespace: str,
                doc: dict[str, object],
                *,
                doc_id: str | None = None,
            ) -> str:
                return ""

        with pytest.raises(TypeError):
            Partial()  # type: ignore[abstract]

    def test_valid_subclass(self) -> None:
        class Full(DocStoreBackend):
            async def insert(
                self,
                namespace: str,
                doc: dict[str, object],
                *,
                doc_id: str | None = None,
            ) -> str:
                return ""

            async def get(
                self, namespace: str, doc_id: str
            ) -> dict[str, object] | None:
                return None

            async def update(
                self, namespace: str, doc_id: str, patch: dict[str, object]
            ) -> bool:
                return False

            async def delete(self, namespace: str, doc_id: str) -> bool:
                return False

            async def find(
                self,
                namespace: str,
                *,
                filters: dict[str, object] | None = None,
                limit: int = 100,
                offset: int = 0,
            ) -> list[dict[str, object]]:
                return []

            async def count(
                self, namespace: str, filters: dict[str, object] | None = None
            ) -> int:
                return 0

        assert Full() is not None
