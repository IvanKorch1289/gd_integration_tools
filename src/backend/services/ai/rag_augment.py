"""AugmentResult + Freshness — структурированный ответ RAG (Sprint 9 K3 W4 + K4 W3).

Раздел A-7 из техдолга: класс :class:`AugmentResult` отсутствовал в
``services/ai/rag_service.py``; теперь живёт отдельным модулем без
циклической зависимости.

Дополнительно (K4 W3): :class:`FreshnessLabel` — метка ``fresh/stale/expired``
для отображения в UI и для отбрасывания результатов старше TTL.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

__all__ = (
    "AugmentResult",
    "FreshnessLabel",
    "compute_freshness",
)


class FreshnessLabel(StrEnum):
    """Метка свежести retrieved-чанка.

    Attributes:
        FRESH: ingested_at < soft_threshold_hours.
        STALE: soft_threshold_hours <= ingested_at < hard_threshold_hours.
        EXPIRED: ingested_at >= hard_threshold_hours (отбрасывать).
    """

    FRESH = "fresh"
    STALE = "stale"
    EXPIRED = "expired"


def compute_freshness(
    *,
    ingested_at: datetime | None,
    soft_hours: float = 72.0,
    hard_hours: float = 168.0,
    now: datetime | None = None,
) -> FreshnessLabel:
    """Вернуть метку свежести по разнице ``now - ingested_at``.

    Args:
        ingested_at: timestamp ingest'а чанка (UTC). None → expired.
        soft_hours: порог fresh→stale (default 72h = 3 дня).
        hard_hours: порог stale→expired (default 168h = 7 дней).
        now: override текущего времени (для тестов).

    Returns:
        :class:`FreshnessLabel`.
    """
    if ingested_at is None:
        return FreshnessLabel.EXPIRED
    if ingested_at.tzinfo is None:
        ingested_at = ingested_at.replace(tzinfo=timezone.utc)
    current = now or datetime.now(timezone.utc)
    age_hours = (current - ingested_at).total_seconds() / 3600.0
    if age_hours < soft_hours:
        return FreshnessLabel.FRESH
    if age_hours < hard_hours:
        return FreshnessLabel.STALE
    return FreshnessLabel.EXPIRED


@dataclass(slots=True)
class AugmentResult:
    """Структурированный результат :meth:`RAGService.augment`.

    Attributes:
        prompt: финальный prompt с inject'ом контекста.
        citations: список ``{doc_id, chunk_idx, namespace, score, freshness}``.
        used_results: число чанков, реально использованных в prompt
            (после фильтрации по freshness).
        skipped_expired: число чанков отброшенных как expired.
        namespace: namespace из запроса (для UI badge).
        top_k: использованный top_k параметр.
        freshness_distribution: ``{fresh, stale, expired}`` → count.
        worst_freshness: худшая метка из использованных (для UI badge).
    """

    prompt: str
    citations: list[dict[str, Any]] = field(default_factory=list)
    used_results: int = 0
    skipped_expired: int = 0
    namespace: str | None = None
    top_k: int = 5
    freshness_distribution: dict[str, int] = field(default_factory=dict)
    worst_freshness: FreshnessLabel = FreshnessLabel.FRESH

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready форма для API/UI."""
        return {
            "prompt": self.prompt,
            "citations": self.citations,
            "used_results": self.used_results,
            "skipped_expired": self.skipped_expired,
            "namespace": self.namespace,
            "top_k": self.top_k,
            "freshness_distribution": self.freshness_distribution,
            "worst_freshness": self.worst_freshness.value,
        }


def build_augment_result(
    *,
    prompt: str,
    raw_results: list[dict[str, Any]],
    namespace: str | None,
    top_k: int,
    max_staleness_hours: float | None = None,
) -> AugmentResult:
    """Построить :class:`AugmentResult` из raw vector-store результатов.

    Args:
        prompt: уже обогащённый prompt из :meth:`augment_prompt`.
        raw_results: список ``{document, metadata: {doc_id, chunk_idx,
            ingested_at, ttl_hours?}, score}``.
        namespace: namespace из запроса.
        top_k: использованный top_k.
        max_staleness_hours: если задан, чанки старше отбрасываются как
            expired (используется в DSL processor ``.rag_query(...)``).

    Returns:
        :class:`AugmentResult`.
    """
    citations: list[dict[str, Any]] = []
    distribution = {label.value: 0 for label in FreshnessLabel}
    skipped = 0
    worst = FreshnessLabel.FRESH
    order = {
        FreshnessLabel.FRESH: 0,
        FreshnessLabel.STALE: 1,
        FreshnessLabel.EXPIRED: 2,
    }

    for raw in raw_results:
        meta = raw.get("metadata") or {}
        ingested = meta.get("ingested_at")
        if isinstance(ingested, str):
            try:
                ingested_dt = datetime.fromisoformat(ingested.replace("Z", "+00:00"))
            except ValueError:
                ingested_dt = None
        elif isinstance(ingested, datetime):
            ingested_dt = ingested
        else:
            ingested_dt = None
        ttl_hours = float(meta.get("ttl_hours") or 168.0)

        label = compute_freshness(
            ingested_at=ingested_dt,
            soft_hours=72.0,
            hard_hours=ttl_hours,
        )
        distribution[label.value] += 1

        if max_staleness_hours is not None and ingested_dt is not None:
            age_hours = (datetime.now(timezone.utc) - ingested_dt).total_seconds() / 3600.0
            if age_hours > max_staleness_hours:
                skipped += 1
                continue

        if order[label] > order[worst]:
            worst = label

        citations.append(
            {
                "doc_id": meta.get("doc_id"),
                "chunk_idx": meta.get("chunk_idx"),
                "namespace": meta.get("namespace") or namespace,
                "score": raw.get("score"),
                "freshness": label.value,
                "ingested_at": ingested_dt.isoformat() if ingested_dt else None,
            }
        )

    return AugmentResult(
        prompt=prompt,
        citations=citations,
        used_results=len(citations),
        skipped_expired=skipped,
        namespace=namespace,
        top_k=top_k,
        freshness_distribution=distribution,
        worst_freshness=worst,
    )
