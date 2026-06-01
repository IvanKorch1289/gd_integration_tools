"""Auto-generated from ai_processors.py — single processor files."""

from __future__ import annotations

from typing import Any, Callable

import orjson

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor


class RagPIIRedactionProcessor(BaseProcessor):
    """PII-маскер для retrieved RAG chunks (Sprint 11 K1 W1).

    Применяется после :class:`RagQueryProcessor` к exchange property
    (``augment_result`` или указанному ``input_property``); маскирует
    ``citations[*].content``, ``documents[*].content`` и ``prompt``
    через :func:`services.ai.pii.retrieval_masker.mask_augment_result`.

    Активируется при ``feature_flags.rag_pii_retrieval_mask=True``
    (capability ``ai.rag.pii_redaction``). При OFF — passthrough без
    модификации payload.

    Usage::

        .rag_query(output_property="augment_result")
        .rag_pii_redact(input_property="augment_result")
        .llm_call(...)

    Безопасно для downstream consumers — input копируется (не мутируется).
    """

    def __init__(
        self,
        input_property: str = "augment_result",
        output_property: str | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(name)
        self._input_property = input_property
        self._output_property = output_property or input_property

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        from src.backend.core.config.features import feature_flags

        if not feature_flags.rag_pii_retrieval_mask:
            return
        payload = exchange.properties.get(self._input_property)
        if not isinstance(payload, dict):
            return
        from src.backend.services.ai.pii.retrieval_masker import mask_augment_result

        masked = mask_augment_result(payload)
        exchange.set_property(self._output_property, masked)

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {}
        if self._input_property != "augment_result":
            spec["input_property"] = self._input_property
        if self._output_property != self._input_property:
            spec["output_property"] = self._output_property
        return {"rag_pii_redact": spec}
