"""Auto-generated from ai_processors.py — single processor files."""

from __future__ import annotations

from typing import Any

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor


class RagIngestProcessor(BaseProcessor):
    """RAG ingest: добавление документа в vector store (S11 K3 W2).

    Принимает body как контент или явный ``source_property`` —
    отправляет в :meth:`RAGService.ingest`. Параметр ``modal``
    сохраняется в metadata как ``modal`` для downstream-консьюмеров
    мультимодального индекса (text/image/audio/video).

    Usage::

        .rag_ingest(
            source_property="document",
            modal="text",
            collection="docs",
        )

    Property ``ingest_doc_id`` хранит возвращённый id документа.
    """

    def __init__(
        self,
        source_property: str | None = None,
        modal: str = "text",
        collection: str = "default",
        output_property: str = "ingest_doc_id",
        name: str | None = None,
    ) -> None:
        super().__init__(name)
        self._source_property = source_property
        self._modal = modal
        self._collection = collection
        self._output_property = output_property

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        if self._source_property:
            content = exchange.get_property(self._source_property)
        else:
            content = exchange.in_message.body
        if not content:
            exchange.set_property(self._output_property, None)
            return
        text = content if isinstance(content, str) else str(content)
        from src.backend.services.ai.rag_service import get_rag_service

        rag = get_rag_service()
        doc_id = await rag.ingest(
            content=text,
            metadata={"modal": self._modal, "collection": self._collection},
            namespace=self._collection,
        )
        exchange.set_property(self._output_property, doc_id)

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {"collection": self._collection}
        if self._source_property is not None:
            spec["source_property"] = self._source_property
        if self._modal != "text":
            spec["modal"] = self._modal
        if self._output_property != "ingest_doc_id":
            spec["output_property"] = self._output_property
        return {"rag_ingest": spec}
