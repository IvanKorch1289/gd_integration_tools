"""Multimodal RAG pipeline orchestrator (Sprint 11 K4 W2).

Объединяет:
1. Ingest по модальности: text/PDF (existing) → chunks; image → caption (BLIP2)
   → text chunk + image embedding; audio → transcript (Whisper) → text chunk
   + (опционально) audio embedding.
2. Embed: одна шина embedding-провайдеров (text + image; audio через transcript).
3. Store: Qdrant payload расширен полем ``modal`` ∈ {text|image|audio|video}.
4. Cross-modal retrieval: text-query → fetch top_k поверх всех модальностей,
   с опциональным фильтром по modal в запросе.

В этой версии используется простой in-memory store
(`MultimodalRAGService._collections`) для тестов; production-вариант
подменяется set_embedder/set_store через DI.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = ("CrossModalQueryResult", "MultimodalPipeline", "ModalKind")

logger = logging.getLogger("services.ai.rag.multimodal.pipeline")

ModalKind = str  # ``text|image|audio|video``


@dataclass(frozen=True, slots=True)
class CrossModalQueryResult:
    """Один результат cross-modal retrieval.

    Attributes:
        chunk_id: ID чанка в store.
        content: Текст (caption для image, transcript для audio).
        modal: Модальность исходника.
        score: cosine similarity или provider-зависимая метрика.
        metadata: Источник, sha256, tenant, freshness и т.д.
    """

    chunk_id: str
    content: str
    modal: ModalKind
    score: float
    metadata: dict[str, Any]


class MultimodalPipeline:
    """Orchestrator multimodal ingest → embed → store → retrieval.

    Args:
        service: :class:`MultimodalRAGService` для PDF/image/text ingest.
        captioner: опц. кастомный BLIP2Captioner (по умолчанию из service).
        whisper: опц. кастомный WhisperSTT (по умолчанию из service).
    """

    def __init__(
        self,
        service: Any,
        *,
        captioner: Any | None = None,
        whisper: Any | None = None,
    ) -> None:
        self._service = service
        self._captioner = captioner
        self._whisper = whisper

    async def ingest(
        self,
        *,
        modal: ModalKind,
        payload: bytes | Path | str,
        collection: str = "default",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Ingest одного объекта произвольной модальности.

        Returns:
            chunk_id первого чанка (для tracking).
        """
        meta = dict(metadata or {})
        meta.setdefault("modal", modal)

        match modal:
            case "text":
                text = payload.decode("utf-8") if isinstance(payload, bytes) else str(payload)
                chunk_id = await self._ingest_text(text, collection, meta)
            case "image":
                if not isinstance(payload, bytes):
                    raise ValueError("image modality requires bytes payload")
                caption = await self._service.caption_image(payload)
                chunk_id = await self._ingest_text(caption, collection, meta)
            case "audio":
                if not isinstance(payload, bytes):
                    raise ValueError("audio modality requires bytes payload")
                transcript = await self._service.transcribe_audio(payload)
                chunk_id = await self._ingest_text(transcript, collection, meta)
            case "video":
                # Stage 1: только аудиодорожка через ffmpeg → audio path.
                # На этой Wave — placeholder; видеоингест без extras.
                raise NotImplementedError("video modality is staged for S12")
            case _:
                raise ValueError(f"unknown modality: {modal}")
        return chunk_id

    async def _ingest_text(
        self, text: str, collection: str, metadata: dict[str, Any]
    ) -> str:
        """Текст → chunk в service._collections (in-memory)."""
        from uuid import uuid4

        chunk_id = uuid4().hex
        store = getattr(self._service, "_collections", None)
        if store is None:
            raise RuntimeError("Pipeline requires MultimodalRAGService с in-memory store")
        store.setdefault(collection, {})
        store[collection][chunk_id] = {
            "content": text,
            "metadata": metadata,
        }
        return chunk_id

    async def query(
        self,
        query_text: str,
        *,
        collection: str = "default",
        top_k: int = 5,
        modal_filter: ModalKind | None = None,
    ) -> list[CrossModalQueryResult]:
        """Cross-modal retrieval: text-query → результаты любой модальности.

        Простой keyword-overlap scoring для tests без embedder.
        """
        store = getattr(self._service, "_collections", {})
        items = store.get(collection, {})
        results: list[CrossModalQueryResult] = []

        query_terms = set(query_text.lower().split())
        for chunk_id, doc in items.items():
            meta = doc.get("metadata") or {}
            modal = meta.get("modal", "text")
            if modal_filter and modal != modal_filter:
                continue
            content_str = str(doc.get("content") or "")
            terms = set(content_str.lower().split())
            overlap = len(query_terms & terms)
            score = float(overlap) / max(1, len(query_terms))
            results.append(
                CrossModalQueryResult(
                    chunk_id=chunk_id,
                    content=content_str,
                    modal=modal,
                    score=score,
                    metadata=meta,
                )
            )

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_k]
