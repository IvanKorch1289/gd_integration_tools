"""Unit tests for src.backend.core.interfaces.search."""

from __future__ import annotations

from src.backend.core.interfaces.search import SearchClient


class TestSearchClient:
    def test_is_runtime_checkable(self) -> None:
        class Fake:
            async def index_document(
                self, index: str, document: dict[str, object], doc_id: str | None = None
            ) -> dict[str, object]:
                return {}

            async def bulk_index(
                self,
                index: str,
                documents: list[dict[str, object]],
                id_field: str | None = None,
            ) -> dict[str, object]:
                return {}

            async def search(
                self,
                index: str,
                query: str | dict[str, object],
                size: int = 10,
                from_: int = 0,
                sort: list[dict[str, object]] | None = None,
            ) -> list[dict[str, object]]:
                return []

            async def aggregate(
                self,
                index: str,
                aggs: dict[str, object],
                query: dict[str, object] | None = None,
            ) -> dict[str, object]:
                return {}

            async def aggregate_terms(
                self,
                index: str,
                field: str,
                *,
                filters: dict[str, object] | None = None,
                size: int = 20,
            ) -> dict[str, object]:
                return {}

            async def delete_document(self, index: str, doc_id: str) -> bool:
                return False

            async def create_index(
                self, index: str, mappings: dict[str, object] | None = None
            ) -> None:
                pass

            async def ping(self) -> bool:
                return True

        assert isinstance(Fake(), SearchClient)

    def test_missing_method_fails(self) -> None:
        class Bad:
            pass

        assert not isinstance(Bad(), SearchClient)
