"""RLMFeedbackProcessor — Reinforcement Learning from Memory (Wave D.6).

Принимает feedback-события ('good' / 'bad' / 'unclear') и применяет их
к метаданным semantic-entry:

* ``good`` → ``rlm_boost++``;
* ``bad`` → ``rlm_penalty++``;
* при накоплении ``rlm_penalty`` ≥ ``rlm_reindex_threshold`` —
  публикуется hint для reindex (event log / metric).

Финальный re-rank в :meth:`SemanticSearch.search()` применяет формулу
``score_adjusted = score * (1 + (boost - penalty) * factor)`` где
``factor = langmem_settings.rlm_boost_factor``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from src.backend.infrastructure.logging.factory import get_logger

logger = get_logger(__name__)

__all__ = ("RLMConsolidator", "RLMFeedbackProcessor", "RLMSignal")


@dataclass(slots=True)
class RLMSignal:
    """Запись о применённом feedback."""

    doc_id: str
    label: str
    new_boost: int
    new_penalty: int
    reindex_hinted: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "label": self.label,
            "new_boost": self.new_boost,
            "new_penalty": self.new_penalty,
            "reindex_hinted": self.reindex_hinted,
        }


class RLMFeedbackProcessor:
    """Обновляет boost/penalty в metadata semantic-entry."""

    def __init__(
        self,
        *,
        langmem_service: Any | None = None,
        reindex_threshold: int | None = None,
    ) -> None:
        self._langmem = langmem_service
        if reindex_threshold is None:
            from src.backend.core.config.ai_2026 import langmem_settings

            reindex_threshold = langmem_settings.rlm_reindex_threshold
        self._reindex_threshold = int(reindex_threshold)

    def _ensure_langmem(self) -> Any:
        if self._langmem is not None:
            return self._langmem
        from src.backend.services.ai.langmem_service import get_langmem_service

        self._langmem = get_langmem_service()
        return self._langmem

    async def on_feedback_received(
        self, *, doc_id: str, label: Literal["good", "bad", "unclear"]
    ) -> RLMSignal:
        """Обновляет ``rlm_boost``/``rlm_penalty`` для ``doc_id``.

        Args:
            doc_id: идентификатор semantic-entry в Qdrant.
            label: метка пользователя.

        Returns:
            :class:`RLMSignal` с новыми значениями счётчиков.
        """
        langmem = self._ensure_langmem()
        client = getattr(langmem, "_client", None)
        if client is None:
            logger.debug("RLM: qdrant client недоступен — feedback не применён")
            return RLMSignal(
                doc_id=doc_id,
                label=label,
                new_boost=0,
                new_penalty=0,
                reindex_hinted=False,
            )

        try:
            payload = await _fetch_payload(client, langmem._collection, doc_id)
        except Exception as exc:
            logger.debug("RLM fetch payload failed: %s", exc)
            payload = {}

        boost = int(payload.get("rlm_boost", 0) or 0)
        penalty = int(payload.get("rlm_penalty", 0) or 0)
        if label == "good":
            boost += 1
        elif label == "bad":
            penalty += 1
        else:
            pass

        payload["rlm_boost"] = boost
        payload["rlm_penalty"] = penalty

        try:
            await _set_payload(client, langmem._collection, doc_id, payload)
        except Exception as exc:
            logger.debug("RLM set payload failed: %s", exc)

        reindex_hinted = penalty >= self._reindex_threshold
        if reindex_hinted:
            logger.info(
                "RLM: penalty=%d ≥ threshold=%d → reindex hint emitted (doc=%s)",
                penalty,
                self._reindex_threshold,
                doc_id,
            )
        return RLMSignal(
            doc_id=doc_id,
            label=label,
            new_boost=boost,
            new_penalty=penalty,
            reindex_hinted=reindex_hinted,
        )

    @staticmethod
    def adjust_score(*, score: float, boost: int, penalty: int) -> float:
        """Re-rank: ``score * (1 + (boost - penalty) * factor)``."""
        from src.backend.core.config.ai_2026 import langmem_settings

        if not langmem_settings.rlm_enabled:
            return score
        factor = langmem_settings.rlm_boost_factor
        delta = (int(boost) - int(penalty)) * factor
        return float(score) * (1.0 + delta)


async def _fetch_payload(client: Any, collection: str, doc_id: str) -> dict[str, Any]:
    retrieve = getattr(client, "retrieve", None)
    if retrieve is None:
        return {}
    points = await retrieve(collection=collection, ids=[doc_id])
    if not points:
        return {}
    first = points[0]
    return dict(getattr(first, "payload", None) or first.get("payload", {}) or {})


async def _set_payload(
    client: Any, collection: str, doc_id: str, payload: dict[str, Any]
) -> None:
    set_payload = getattr(client, "set_payload", None)
    if set_payload is None:
        upsert = getattr(client, "upsert", None)
        if upsert is None:
            return
        await upsert(collection=collection, points=[{"id": doc_id, "payload": payload}])
        return
    await set_payload(collection=collection, payload=payload, points=[doc_id])


class RLMConsolidator:
    """Фоновый consolidator для semantic memory — re-embed + reindex."""

    def __init__(
        self,
        qdrant_client,
        embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2",
        threshold: float = 0.3,
    ):
        self.qdrant = qdrant_client
        self.embedding_model = embedding_model
        self.threshold = threshold

    async def consolidate(self, batch_size: int = 100) -> dict:
        """
        1. Fetch entries with penalty > threshold from Qdrant.
        2. Re-embed via current embedding model.
        3. Upsert updated vectors.
        4. Delete stale entries.
        5. Return consolidation report.
        """
        import datetime

        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(self.embedding_model)

        # Step 1: scroll all entries, filter those with penalty > threshold
        all_results = []
        offset_token = None
        penalty_threshold = float(self.threshold)
        while True:
            scroll_page = await self.qdrant.scroll(
                collection="langmem_semantic",
                scroll_filter={
                    "must": [{"key": "rlm_penalty", "range": {"gt": penalty_threshold}}]
                },
                limit=batch_size,
                offset=offset_token,
                with_payload=True,
            )
            page_results = getattr(scroll_page, "points", scroll_page.get("points", []))
            all_results.extend(page_results)
            offset_token = getattr(scroll_page, "next_page_offset", None)
            if offset_token is None or len(page_results) == 0:
                break
        results = all_results[:batch_size]

        if not results:
            return {"consolidated": 0, "reindexed": 0, "deleted": 0}

        # Step 2: re-embed
        texts = [r.payload.get("text", "") for r in results]
        vectors = model.encode(texts).tolist()

        # Step 3: upsert re-embedded vectors + reset penalty (marks as reindexed)
        from datetime import UTC

        now = datetime.datetime.now(UTC).isoformat()
        points = []
        for r, vector in zip(results, vectors):
            p = dict(r.payload) if hasattr(r, "payload") else r.get("payload", {})
            p["reindexed_at"] = now
            p["rlm_penalty"] = 0  # reset after successful reindex
            point_id = r.id if hasattr(r, "id") else r.get("id")
            points.append({"id": point_id, "vector": vector, "payload": p})
        await self.qdrant.upsert(collection="langmem_semantic", points=points)

        # Step 4: NO delete — upsert is in-place update, deleting would remove
        # the freshly reindexed records. Reset penalty prevents re-selection.

        return {
            "consolidated": len(results),
            "reindexed": len(results),
            "penalty_reset": len(results),
        }

    async def schedule_reindex(self, doc_ids: list[str]) -> dict:
        """
        Reindex specific documents by ID.
        Triggered when penalty >= reindex_threshold.
        """
        if not doc_ids:
            return {"reindexed": 0}

        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(self.embedding_model)

        recs = await self.qdrant.retrieve(collection="langmem_semantic", ids=doc_ids)
        if not recs:
            return {"reindexed": 0}

        texts = [r.payload.get("text", "") for r in recs]
        vectors = model.encode(texts).tolist()

        points = [
            {"id": r.id, "vector": v, "payload": r.payload}
            for r, v in zip(recs, vectors)
        ]
        await self.qdrant.upsert(collection="langmem_semantic", points=points)

        return {"reindexed": len(points)}
