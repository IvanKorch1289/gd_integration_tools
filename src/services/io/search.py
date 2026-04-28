"""SearchService — полнотекстовый поиск через Elasticsearch."""

from __future__ import annotations

from typing import Any

from src.infrastructure.clients.storage.elasticsearch import (
    ElasticSearchClient,
    get_elasticsearch_client,
)

__all__ = ("SearchService", "get_search_service")


class SearchService:
    """Сервис поиска — индексация, полнотекстовый поиск, агрегации."""

    def __init__(self, client: ElasticSearchClient) -> None:
        self._client = client

    async def index_document(
        self, index: str, document: dict[str, Any], doc_id: str | None = None
    ) -> dict[str, Any]:
        """Индексирует один документ."""
        return await self._client.index_document(index, document, doc_id)

    async def bulk_index(
        self, index: str, documents: list[dict[str, Any]], id_field: str | None = None
    ) -> dict[str, Any]:
        """Массовая индексация документов."""
        return await self._client.bulk_index(index, documents, id_field)

    async def search(
        self,
        index: str,
        query: str | dict[str, Any],
        size: int = 10,
        from_: int = 0,
        sort: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Полнотекстовый поиск."""
        return await self._client.search(
            index, query, size=size, from_=from_, sort=sort
        )

    async def aggregate(
        self, index: str, aggs: dict[str, Any], query: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Запрос агрегации."""
        return await self._client.aggregate(index, aggs, query)

    async def delete_document(self, index: str, doc_id: str) -> bool:
        """Удаляет документ по ID."""
        return await self._client.delete_document(index, doc_id)

    async def ensure_index(
        self, index: str, mappings: dict[str, Any] | None = None
    ) -> None:
        """Создаёт индекс если не существует."""
        await self._client.create_index(index, mappings)

    async def health(self) -> bool:
        """Проверка доступности Elasticsearch."""
        return await self._client.ping()


_search_service_instance: SearchService | None = None


def get_search_service() -> SearchService:
    global _search_service_instance
    if _search_service_instance is None:
        _search_service_instance = SearchService(client=get_elasticsearch_client())
    return _search_service_instance
