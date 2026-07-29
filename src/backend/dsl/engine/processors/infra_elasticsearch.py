"""DSL processor ``infra_elasticsearch_search`` (cycle 26, user-requested wrap of unused dep).

Elasticsearch full-text search через facade. Pattern follows
infra_mongodb_find (S170 M2) — thin wrapper around facade via DI.

YAML:
    - infra_elasticsearch_search:
        index: documents
        query:
          match:
            content: "fastapi"
        size: 10
        to: body.results
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.registry import processor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange


@processor(
    "infra_elasticsearch_search",
    namespace="infra",
    spec_schema={
        "type": "object",
        "properties": {
            "index": {"type": "string"},
            "query": {"type": "object"},
            "size": {"type": "integer", "default": 10},
            "to": {"type": "string"},
        },
        "required": ["index", "query"],
    },
    capabilities=("db.read.elasticsearch",),
    meta={"tier": 1, "category": "infra"},
)
class InfraElasticsearchSearchProcessor(BaseProcessor):
    """ES processor: InfraElasticsearchSearchProcessor (search/index operation)."""
    def __init__(
        self,
        index: str,
        query: dict[str, Any],
        *,
        size: int = 10,
        to: str = "body.results",
    ) -> None:
        super().__init__(name=f"infra_elasticsearch_search:{index}")
        self.index = index
        self.query = query
        self.size = size
        self.target = to

    async def process(self, exchange: "Exchange[Any]", context: "ExecutionContext") -> None:
        """ES search: выполнить query и положить results в exchange."""
        from src.backend.core.di.providers.infrastructure_locator import (
            get_elasticsearch_client_class,
        )
        client = get_elasticsearch_client_class()(context)
        results = await client.search(index=self.index, query=self.query, size=self.size)
        self.set_result(exchange, self.target, results)


@processor(
    "infra_elasticsearch_index",
    namespace="infra",
    spec_schema={
        "type": "object",
        "properties": {
            "index": {"type": "string"},
            "document": {"type": "object"},
            "doc_id": {"type": ["string", "null"]},
            "to": {"type": "string"},
        },
        "required": ["index", "document"],
    },
    capabilities=("db.write.elasticsearch",),
    meta={"tier": 1, "category": "infra"},
)
class InfraElasticsearchIndexProcessor(BaseProcessor):
    """ES processor: InfraElasticsearchIndexProcessor (search/index operation)."""
    def __init__(
        self,
        index: str,
        document: dict[str, Any],
        *,
        doc_id: str | None = None,
        to: str = "body.doc_id",
    ) -> None:
        super().__init__(name=f"infra_elasticsearch_index:{index}")
        self.index = index
        self.document = document
        self.doc_id = doc_id
        self.target = to

    async def process(self, exchange: "Exchange[Any]", context: "ExecutionContext") -> None:
        """ES index: отправить document на indexing."""
        from src.backend.core.di.providers.infrastructure_locator import (
            get_elasticsearch_client_class,
        )
        client = get_elasticsearch_client_class()(context)
        doc_id = await client.index_document(
            index=self.index,
            document=self.document,
            doc_id=self.doc_id,
        )
        self.set_result(exchange, self.target, doc_id)
