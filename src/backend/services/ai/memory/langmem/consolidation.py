"""ConsolidationEngine — episodic → semantic (LLM-summarization, Wave D.6).

Алгоритм:

1. Fetch episodic с ``occurred_at >= since``.
2. Кластеризовать по ``(tenant, session_id)``.
3. Для каждого кластера ``size >= consolidation_min_cluster_size`` —
   попросить LLM выделить 3-5 атомарных фактов в JSON-формате.
4. Факты с ``confidence >= consolidation_confidence_threshold`` —
   сохранить в semantic-tier через :class:`LangMemService.add_semantic`.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import orjson

logger = logging.getLogger(__name__)

__all__ = ("ConsolidationEngine", "ConsolidationReport", "ExtractedFact")


@dataclass(slots=True)
class ExtractedFact:
    """Один факт, извлечённый LLM из эпизодов."""

    text: str
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "confidence": self.confidence}


@dataclass(slots=True)
class ConsolidationReport:
    """Сводка по запуску consolidate()."""

    processed: int = 0
    clusters: int = 0
    facts_extracted: int = 0
    facts_persisted: int = 0
    skipped_clusters: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "processed": self.processed,
            "clusters": self.clusters,
            "facts_extracted": self.facts_extracted,
            "facts_persisted": self.facts_persisted,
            "skipped_clusters": self.skipped_clusters,
            "errors": list(self.errors),
        }


_SUMMARIZER_TEMPLATE = (
    "Ты — менеджер памяти. Прочитай диалог и выдели 3-5 АТОМАРНЫХ фактов, "
    "которые стоит сохранить надолго. Каждому факту присвой уверенность "
    "(0.0-1.0). Ответ — строго валидный JSON-массив объектов: "
    '[{{"fact": "...", "confidence": 0.7}}, ...]. '
    "Без markdown, без пояснений.\n\nДИАЛОГ:\n{dialog}"
)


class ConsolidationEngine:
    """LLM-движок консолидации episodic → semantic."""

    def __init__(
        self,
        *,
        langmem_service: Any | None = None,
        gateway: Any | None = None,
        summarizer_template: str = _SUMMARIZER_TEMPLATE,
    ) -> None:
        self._langmem = langmem_service
        self._gateway = gateway
        self._template = summarizer_template

    def _ensure_langmem(self) -> Any:
        if self._langmem is not None:
            return self._langmem
        from src.backend.services.ai.langmem_service import get_langmem_service

        self._langmem = get_langmem_service()
        return self._langmem

    def _ensure_gateway(self) -> Any:
        if self._gateway is not None:
            return self._gateway
        from src.backend.services.ai.gateway.client import get_litellm_gateway

        self._gateway = get_litellm_gateway()
        return self._gateway

    async def run(
        self, *, since: datetime | None = None, batch_size: int = 50
    ) -> ConsolidationReport:
        """Главный entrypoint. Возвращает :class:`ConsolidationReport`."""
        from src.backend.core.config.ai_2026 import langmem_settings

        report = ConsolidationReport()
        langmem = self._ensure_langmem()
        episodes = await self._fetch_episodes(langmem, since=since, limit=batch_size)
        report.processed = len(episodes)
        if not episodes:
            return report

        clusters = _cluster_by_session(episodes)
        report.clusters = len(clusters)

        gateway = self._ensure_gateway()
        for key, group in clusters.items():
            if len(group) < langmem_settings.consolidation_min_cluster_size:
                report.skipped_clusters += 1
                continue
            facts = await self._extract_facts(group, gateway=gateway)
            report.facts_extracted += len(facts)
            for fact in facts:
                if (
                    fact.confidence
                    < langmem_settings.consolidation_confidence_threshold
                ):
                    continue
                try:
                    await langmem.add_semantic(
                        text=fact.text,
                        tenant=key[0] if key[0] else None,
                        meta={
                            "source": "consolidation",
                            "session_id": key[1],
                            "confidence": fact.confidence,
                        },
                    )
                    report.facts_persisted += 1
                except Exception as exc:  # noqa: BLE001
                    report.errors.append(str(exc))
                    logger.debug("ConsolidationEngine persist failed: %s", exc)
        return report

    async def _fetch_episodes(
        self, langmem: Any, *, since: datetime | None, limit: int
    ) -> list[dict[str, Any]]:
        recall = getattr(langmem, "recall", None)
        if recall is None:
            return []
        try:
            episodes = await recall(kind="episodic", limit=limit)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Episodic recall failed: %s", exc)
            return []
        if since is None:
            return list(episodes)
        cutoff = since.isoformat() if isinstance(since, datetime) else str(since)
        return [ep for ep in episodes if (ep.get("occurred_at") or "") >= cutoff]

    async def _extract_facts(
        self, episodes: list[dict[str, Any]], *, gateway: Any
    ) -> list[ExtractedFact]:
        dialog = "\n".join(
            f"{e.get('role', 'user')}: {e.get('content', '')}" for e in episodes
        )
        prompt = self._template.format(dialog=dialog)
        try:
            response = await gateway.acompletion(
                messages=[{"role": "user", "content": prompt}]
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("LLM consolidate call failed: %s", exc)
            return []
        text = _extract_text(response)
        return _parse_facts(text)


def _cluster_by_session(
    episodes: list[dict[str, Any]],
) -> dict[tuple[str | None, str | None], list[dict[str, Any]]]:
    out: dict[tuple[str | None, str | None], list[dict[str, Any]]] = defaultdict(list)
    for ep in episodes:
        tenant = ep.get("tenant") or (ep.get("meta") or {}).get("tenant")
        session = ep.get("session_id")
        out[(tenant, session)].append(ep)
    return out


def _extract_text(response: Any) -> str:
    choices = getattr(response, "choices", None)
    if choices is None and isinstance(response, dict):
        choices = response.get("choices") or []
    if not choices:
        return ""
    first = choices[0]
    message = getattr(first, "message", None)
    if message is None and isinstance(first, dict):
        message = first.get("message")
    if message is None:
        return ""
    content = getattr(message, "content", None)
    if content is None and isinstance(message, dict):
        content = message.get("content")
    return str(content or "")


def _parse_facts(text: str) -> list[ExtractedFact]:
    text = (text or "").strip()
    if not text:
        return []
    try:
        data = orjson.loads(text)
    except Exception as _:  # noqa: BLE001
        return []
    facts: list[ExtractedFact] = []
    if not isinstance(data, list):
        return facts
    for entry in data:
        if not isinstance(entry, dict):
            continue
        body = entry.get("fact") or entry.get("text") or ""
        try:
            confidence = float(entry.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        if body:
            facts.append(ExtractedFact(text=str(body), confidence=confidence))
    return facts
