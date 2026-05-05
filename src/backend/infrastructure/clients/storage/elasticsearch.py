"""Async Elasticsearch client — index, search, aggregate, bulk."""

from __future__ import annotations

import logging
from typing import Any

__all__ = ("ElasticSearchClient", "get_elasticsearch_client")

logger = logging.getLogger(__name__)


class ElasticSearchClient:
    """Асинхронный клиент Elasticsearch 8.x.

    Поддерживает: индексацию, полнотекстовый поиск,
    агрегации, bulk operations.
    """

    def __init__(
        self,
        hosts: list[str] | None = None,
        api_key: str | None = None,
        username: str | None = None,
        password: str | None = None,
        verify_certs: bool = True,
        ca_certs: str | None = None,
        request_timeout: int = 30,
        max_retries: int = 3,
        index_prefix: str = "gd_",
    ) -> None:
        self._hosts = hosts or ["http://localhost:9200"]
        self._api_key = api_key
        self._username = username
        self._password = password
        self._verify_certs = verify_certs
        self._ca_certs = ca_certs
        self._request_timeout = request_timeout
        self._max_retries = max_retries
        self._index_prefix = index_prefix
        self._client: Any = None

    def _prefixed(self, index: str) -> str:
        if index.startswith(self._index_prefix):
            return index
        return f"{self._index_prefix}{index}"

    async def connect(self) -> None:
        from elasticsearch import AsyncElasticsearch

        kwargs: dict[str, Any] = {
            "hosts": self._hosts,
            "verify_certs": self._verify_certs,
            "request_timeout": self._request_timeout,
            "max_retries": self._max_retries,
        }

        if self._api_key:
            kwargs["api_key"] = self._api_key
        elif self._username and self._password:
            kwargs["basic_auth"] = (self._username, self._password)

        if self._ca_certs:
            kwargs["ca_certs"] = self._ca_certs

        self._client = AsyncElasticsearch(**kwargs)
        info = await self._client.info()
        logger.info(
            "Elasticsearch connected: %s v%s",
            info["cluster_name"],
            info["version"]["number"],
        )

    async def close(self) -> None:
        if self._client:
            await self._client.close()
            self._client = None
            logger.info("Elasticsearch client disconnected")

    async def _ensure_client(self) -> Any:
        if self._client is None:
            await self.connect()
        return self._client

    async def index_document(
        self, index: str, document: dict[str, Any], doc_id: str | None = None
    ) -> dict[str, Any]:
        """Индексирует один документ."""
        client = await self._ensure_client()
        result = await client.index(
            index=self._prefixed(index), document=document, id=doc_id
        )
        return dict(result)

    async def bulk_index(
        self, index: str, documents: list[dict[str, Any]], id_field: str | None = None
    ) -> dict[str, Any]:
        """Bulk-индексация документов."""
        from elasticsearch.helpers import async_bulk

        client = await self._ensure_client()
        prefixed = self._prefixed(index)

        actions = []
        for doc in documents:
            action: dict[str, Any] = {"_index": prefixed, "_source": doc}
            if id_field and id_field in doc:
                action["_id"] = doc[id_field]
            actions.append(action)

        success, errors = await async_bulk(client, actions, raise_on_error=False)
        logger.info("Bulk indexed %d documents into %s", success, prefixed)
        return {"indexed": success, "errors": errors}

    async def search(
        self,
        index: str,
        query: dict[str, Any] | str,
        size: int = 10,
        from_: int = 0,
        sort: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Полнотекстовый поиск."""
        client = await self._ensure_client()

        if isinstance(query, str):
            body = {"query": {"multi_match": {"query": query, "fields": ["*"]}}}
        else:
            body = {"query": query}

        body["size"] = size
        body["from"] = from_
        if sort:
            body["sort"] = sort

        result = await client.search(index=self._prefixed(index), body=body)

        return [
            {**hit["_source"], "_id": hit["_id"], "_score": hit.get("_score")}
            for hit in result["hits"]["hits"]
        ]

    async def aggregate(
        self, index: str, aggs: dict[str, Any], query: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Запрос агрегации."""
        client = await self._ensure_client()
        body: dict[str, Any] = {"aggs": aggs, "size": 0}
        if query:
            body["query"] = query

        result = await client.search(index=self._prefixed(index), body=body)
        return dict(result["aggregations"])

    async def delete_document(self, index: str, doc_id: str) -> bool:
        """Удаляет документ по ID."""
        client = await self._ensure_client()
        try:
            await client.delete(index=self._prefixed(index), id=doc_id)
            return True
        except ConnectionError, TimeoutError, OSError:
            return False

    async def create_index(
        self, index: str, mappings: dict[str, Any] | None = None
    ) -> None:
        """Создаёт индекс (если не существует)."""
        client = await self._ensure_client()
        prefixed = self._prefixed(index)
        if not await client.indices.exists(index=prefixed):
            body = {"mappings": mappings} if mappings else {}
            await client.indices.create(index=prefixed, body=body)
            logger.info("Index %s created", prefixed)

    async def ensure_indices(
        self,
        names: list[str],
        mappings_by_name: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, bool]:
        """Гарантирует наличие нескольких индексов, возвращает map name → created.

        ``True`` — индекс создан, ``False`` — уже существовал.
        Любые ошибки логируются, но не пробрасываются (опциональный bootstrap).
        """
        result: dict[str, bool] = {}
        try:
            client = await self._ensure_client()
        except Exception as exc:  # noqa: BLE001
            logger.warning("ensure_indices: ES недоступен (%s)", exc)
            return {n: False for n in names}

        for name in names:
            prefixed = self._prefixed(name)
            try:
                exists = await client.indices.exists(index=prefixed)
                if exists:
                    result[name] = False
                    continue
                mappings = (mappings_by_name or {}).get(name)
                body = {"mappings": mappings} if mappings else {}
                await client.indices.create(index=prefixed, body=body)
                logger.info("Index %s created (ensure_indices)", prefixed)
                result[name] = True
            except Exception as exc:  # noqa: BLE001
                logger.warning("ensure_indices(%s) failed: %s", prefixed, exc)
                result[name] = False
        return result

    async def aggregate_terms(
        self,
        index: str,
        field: str,
        *,
        filters: dict[str, Any] | None = None,
        size: int = 20,
    ) -> dict[str, Any]:
        """Высокоуровневая обёртка над ``aggregate``: чистая terms-агрегация.

        ``filters`` транслируется в bool/term-clauses; пустой ``filters``
        означает aggregate-over-all.
        """
        body_query: dict[str, Any] | None = None
        if filters:
            body_query = {
                "bool": {
                    "filter": [
                        {"term": {k: v}} for k, v in filters.items() if v is not None
                    ]
                }
            }
        aggs = {"by_field": {"terms": {"field": field, "size": size}}}
        return await self.aggregate(index, aggs, body_query)

    async def ping(self) -> bool:
        """Проверка доступности Elasticsearch."""
        try:
            client = await self._ensure_client()
            return await client.ping()
        except ConnectionError, TimeoutError, OSError:
            return False


_es_client: ElasticSearchClient | None = None


def _create_elasticsearch_client() -> ElasticSearchClient:
    from src.core.config.elasticsearch import elasticsearch_settings

    return ElasticSearchClient(
        hosts=elasticsearch_settings.hosts,
        api_key=elasticsearch_settings.api_key,
        username=elasticsearch_settings.username,
        password=elasticsearch_settings.password,
        verify_certs=elasticsearch_settings.verify_certs,
        ca_certs=elasticsearch_settings.ca_certs,
        request_timeout=elasticsearch_settings.request_timeout,
        max_retries=elasticsearch_settings.max_retries,
        index_prefix=elasticsearch_settings.index_prefix,
    )


from src.core.di import app_state_singleton


@app_state_singleton("elasticsearch_client", _create_elasticsearch_client)
def get_elasticsearch_client() -> ElasticSearchClient:
    """Возвращает ElasticSearchClient из app.state или lazy-init fallback."""
