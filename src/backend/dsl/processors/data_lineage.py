"""DataLineageProcessor — Data Lineage / Provenance tracking (v21 §2.1).

Closes v21 gap #1 (Data Lineage / Provenance). EU AI Act требует documentation
training data и RAG provenance — tracking source documents, versions, chunks для
каждого LLM response. OpenLineage — open standard для lineage metadata.

Архитектура::

    DataLineageProcessor (in pipeline)
           │
           ├── captures input lineage (body + headers)
           ├── records output lineage (after transform)
           ├── emits LineageEvent через LineageEmitter
           │
           └── stores events в exchange.properties['lineage_event']

Usage в DSL::

    route = (
        RouteBuilder.from_("docs.ingest", source="internal:docs")
        .data_lineage(
            dataset="customer_docs",
            source_uri="s3://docs/customer_{tenant}.json",
            capture_fields=["tenant", "doc_id"],
        )
        .to("ai.rag.index")
        .data_lineage(
            dataset="rag_chunks",
            derive_from="docs.ingest",
            capture_fields=["chunks", "embedding_model"],
        )
        .build()
    )

DI: ``lineage_emitter`` — async callable (event) -> None.
Default: :func:`src.backend.services.lineage.get_lineage_emitter` (in-memory store).
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, ClassVar

from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.processors.base import BaseProcessor, handle_processor_error

if TYPE_CHECKING:
    from src.backend.dsl.builders.base import RouteBuilder
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

__all__ = (
    "DataLineageMixin",
    "DataLineageProcessor",
    "LineageEmitter",
    "LineageEvent",
    "LineageNode",
    "LineageNodeType",
)

_log = logging.getLogger(__name__)


class LineageNodeType(str, Enum):
    """Тип узла в lineage graph."""

    DATASET = "dataset"  # Сырой датасет (CSV, JSON, S3 object)
    PIPELINE = "pipeline"  # Шаг pipeline (route, processor, action)
    MODEL = "model"  # ML/LLM model
    OUTPUT = "output"  # Результат pipeline (response, decision)
    CHUNK = "chunk"  # RAG chunk


@dataclass(frozen=True, slots=True)
class LineageNode:
    """Узел lineage graph.

    Attributes:
        id: Уникальный ID (``f"{type}:{name}"`` или UUID).
        type: Тип узла (dataset/pipeline/model/output/chunk).
        name: Human-readable имя.
        attributes: Метаданные (URI, version, schema, model_id, ...).
    """

    id: str
    type: LineageNodeType
    name: str
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LineageEvent:
    """Один event в lineage stream.

    Attributes:
        event_id: UUID event.
        run_id: Pipeline run ID (для связки events в одном execution).
        event_type: ``"input"`` / ``"output"`` / ``"transform"``.
        node: Узел, который event описывает.
        parent_ids: IDs узлов-источников (откуда данные пришли).
        timestamp: Unix timestamp (sec).
        payload: Полезные данные (chunk_ids, model_id, scores, ...).
    """

    event_id: str
    run_id: str
    event_type: str
    node: LineageNode
    parent_ids: tuple[str, ...] = ()
    timestamp: float = field(default_factory=time.time)
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Сериализация в OpenLineage-compatible dict."""
        return {
            "event_id": self.event_id,
            "run_id": self.run_id,
            "event_type": self.event_type,
            "node": {
                "id": self.node.id,
                "type": self.node.type.value,
                "name": self.node.name,
                "attributes": dict(self.node.attributes),
            },
            "parent_ids": list(self.parent_ids),
            "timestamp": self.timestamp,
            "payload": dict(self.payload),
        }


# Type alias: emitter — async callable принимает LineageEvent.
LineageEmitter = Callable[[LineageEvent], Any]  # Awaitable[None] | None


def _default_lineage_emitter() -> LineageEmitter:
    """Lazy lineage emitter provider (избегает import при test-load)."""
    from src.backend.services.lineage import get_lineage_emitter

    def _e(event: LineageEvent) -> None:
        # Sync wrapper — actual emitter is async-friendly, await in DI.
        emitter = get_lineage_emitter()
        emitter(event)

    return _e


class DataLineageProcessor(BaseProcessor):
    """Захватывает lineage для каждого exchange.

    В pipeline добавляет LineageEvent в ``exchange.properties['lineage_event']``
    и emit-ит через lineage_emitter для downstream-консьюмеров (RAG provenance,
    OpenLineage facade, audit log).
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.PURE
    compensatable: ClassVar[bool] = True

    def __init__(
        self,
        *,
        dataset: str,
        source_uri: str | None = None,
        derive_from: str | None = None,
        capture_fields: list[str] | None = None,
        run_id: str | None = None,
        node_type: LineageNodeType = LineageNodeType.DATASET,
        lineage_emitter: LineageEmitter | None = None,
        event_type: str = "transform",
        name: str | None = None,
    ) -> None:
        """Args:
        dataset: Имя датасета (e.g. ``"customer_docs"``).
        source_uri: URI источника (s3://..., file://..., internal:...).
        derive_from: ID родительского node (для production-lineage).
        capture_fields: Поля из body/headers для payload lineage event.
        run_id: Pipeline run ID (default: auto-generated UUID).
        node_type: LineageNodeType (DATASET / PIPELINE / OUTPUT / ...).
        lineage_emitter: async callable (event) -> None. Default: in-memory store.
        event_type: ``"input"`` / ``"output"`` / ``"transform"``.
        """
        if not dataset:
            raise ValueError("dataset обязателен")
        if event_type not in ("input", "output", "transform"):
            raise ValueError(
                f"event_type должен быть input/output/transform, "
                f"получено {event_type!r}"
            )
        super().__init__(name=name or f"data_lineage_{dataset}")
        self._dataset = dataset
        self._source_uri = source_uri
        self._derive_from = derive_from
        self._capture_fields = capture_fields or []
        self._run_id = run_id or str(uuid.uuid4())
        self._node_type = node_type
        self._emitter: LineageEmitter = lineage_emitter or _default_lineage_emitter()
        self._event_type = event_type

    @handle_processor_error
    async def process(
        self, exchange: Exchange[Any], context: ExecutionContext
    ) -> None:
        """Capture lineage event для текущего exchange.

        1. Extract capture_fields из body/headers
        2. Build LineageNode (dataset, source_uri, attributes)
        3. Build LineageEvent (run_id, parent_ids from derive_from)
        4. Emit через lineage_emitter
        5. Store в exchange.properties['lineage_event'] для downstream
        """
        body = exchange.in_message.body
        headers = exchange.in_message.headers

        # Capture fields
        payload: dict[str, Any] = {}
        for field_name in self._capture_fields:
            if isinstance(body, dict) and field_name in body:
                payload[field_name] = body[field_name]
            elif field_name in headers:
                payload[field_name] = headers[field_name]

        # Build node
        node_attrs: dict[str, Any] = {}
        if self._source_uri:
            node_attrs["source_uri"] = self._source_uri
        node_attrs.update(payload)

        node = LineageNode(
            id=f"{self._node_type.value}:{self._dataset}",
            type=self._node_type,
            name=self._dataset,
            attributes=node_attrs,
        )

        # Parent IDs
        parent_ids: tuple[str, ...] = ()
        if self._derive_from:
            parent_ids = (self._derive_from,)

        # Build event
        event = LineageEvent(
            event_id=str(uuid.uuid4()),
            run_id=self._run_id,
            event_type=self._event_type,
            node=node,
            parent_ids=parent_ids,
            payload=payload,
        )

        # Emit (sync or async)
        emit_result = self._emitter(event)
        if hasattr(emit_result, "__await__"):
            await emit_result

        # Store в exchange для downstream processors
        existing = exchange.properties.get("lineage_events", [])
        if not isinstance(existing, list):
            existing = []
        existing.append(event.to_dict())
        exchange.set_property("lineage_events", existing)
        exchange.set_property("lineage_event", event.to_dict())


class DataLineageMixin:
    """Mixin для :class:`RouteBuilder` — chainable ``.data_lineage(...)``.

    Stateless: ``self._add`` через MRO (контракт см. :class:`RouteBuilder`).
    """

    __slots__ = ()

    def data_lineage(
        self,
        *,
        dataset: str,
        source_uri: str | None = None,
        derive_from: str | None = None,
        capture_fields: list[str] | None = None,
        run_id: str | None = None,
        node_type: LineageNodeType = LineageNodeType.DATASET,
        lineage_emitter: LineageEmitter | None = None,
        event_type: str = "transform",
    ) -> "RouteBuilder":
        """Добавить :class:`DataLineageProcessor` в pipeline.

        Args:
            dataset: Имя датасета (e.g. ``"customer_docs"``).
            source_uri: URI источника (s3://..., file://..., internal:...).
            derive_from: ID родительского node (для production-lineage).
            capture_fields: Поля из body/headers для payload lineage event.
            run_id: Pipeline run ID (default: auto-generated UUID).
            node_type: LineageNodeType (DATASET / PIPELINE / OUTPUT / ...).
            lineage_emitter: async callable (event) -> None. Default: in-memory store.
            event_type: ``"input"`` / ``"output"`` / ``"transform"``.

        Returns:
            :class:`RouteBuilder` для fluent-chaining.
        """
        return self._add(  # type: ignore[attr-defined]
            DataLineageProcessor(
                dataset=dataset,
                source_uri=source_uri,
                derive_from=derive_from,
                capture_fields=capture_fields,
                run_id=run_id,
                node_type=node_type,
                lineage_emitter=lineage_emitter,
                event_type=event_type,
            )
        )
