"""Protocol ``SearchClient`` — контракт search-бэкенда.

Wave 6: вынесено для services/io/search.py, чтобы сервис не импортировал
конкретный ``ElasticSearchClient``. Реализация остаётся в
``infrastructure/clients/storage/elasticsearch.py``.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

__all__ = ("SearchClient",)


@runtime_checkable
class SearchClient(Protocol):
    """Контракт search-бэкенда (Elasticsearch / OpenSearch / SQLite-FTS5)."""

    async def index_document(
        self, index: str, document: dict[str, Any], doc_id: str | None = None
    ) -> dict[str, Any]: ...

    async def bulk_index(
        self, index: str, documents: list[dict[str, Any]], id_field: str | None = None
    ) -> dict[str, Any]: ...

    async def search(
        self,
        index: str,
        query: str | dict[str, Any],
        size: int = 10,
        from_: int = 0,
        sort: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]: ...

    async def aggregate(
        self, index: str, aggs: dict[str, Any], query: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    async def delete_document(self, index: str, doc_id: str) -> bool: ...

    async def create_index(
        self, index: str, mappings: dict[str, Any] | None = None
    ) -> None: ...

    async def ping(self) -> bool: ...
