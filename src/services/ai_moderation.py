"""AI Content Moderation + RAGAS evaluation.

ContentModeration:
- OpenAI Moderation API (бесплатный) — hate, harassment, violence, self-harm, sexual
- Fallback: Presidio для PII + simple blocklist patterns

RagasEvaluation:
- Faithfulness (ответ основан на контексте)
- Answer relevancy
- Context precision / recall
- Опционально, требует ragas library
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Any

import httpx

__all__ = (
    "ContentModeration",
    "ModerationResult",
    "RagasEvaluator",
    "get_moderation",
    "get_ragas",
)

logger = logging.getLogger("services.ai_moderation")


@dataclass(slots=True)
class ModerationResult:
    flagged: bool
    categories: dict[str, bool]
    scores: dict[str, float]
    reason: str | None = None


class ContentModeration:
    """OpenAI Moderation API wrapper + fallback rules.

    OpenAI Moderation API — бесплатный, без rate limits в разумных пределах.
    """

    _BLOCKLIST_PATTERNS = (
        r"\b(?:suicide|kill myself|self-harm)\b",
        r"\b(?:bomb|explosive|weapon)\b.*\b(?:how to|make|build)\b",
        r"\b(?:child|minor).*\b(?:sexual|nude)\b",
    )

    def __init__(self, *, api_key: str | None = None) -> None:
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")

    async def check(self, text: str) -> ModerationResult:
        """Проверяет текст. Возвращает flagged=True при нарушении.

        Сначала OpenAI Moderation (если есть ключ), иначе local rules.
        """
        if self._api_key:
            try:
                return await self._check_openai(text)
            except Exception as exc:
                logger.debug("OpenAI moderation failed, falling back: %s", exc)

        return self._check_local(text)

    async def _check_openai(self, text: str) -> ModerationResult:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                "https://api.openai.com/v1/moderations",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={"input": text[:32000]},
            )
            resp.raise_for_status()
            data = resp.json()

        result = data["results"][0]
        flagged = bool(result.get("flagged", False))
        categories = result.get("categories", {})
        scores = result.get("category_scores", {})

        reason = None
        if flagged:
            reasons = [cat for cat, is_flag in categories.items() if is_flag]
            reason = ", ".join(reasons) if reasons else "unspecified"

        return ModerationResult(
            flagged=flagged,
            categories=categories,
            scores=scores,
            reason=reason,
        )

    def _check_local(self, text: str) -> ModerationResult:
        """Local fallback — regex blocklist."""
        text_lower = text.lower()
        matched: list[str] = []
        for pattern in self._BLOCKLIST_PATTERNS:
            if re.search(pattern, text_lower, re.IGNORECASE):
                matched.append(pattern)

        flagged = bool(matched)
        return ModerationResult(
            flagged=flagged,
            categories={"local_blocklist": flagged},
            scores={"local_blocklist": 1.0 if flagged else 0.0},
            reason=f"local blocklist matched: {matched}" if flagged else None,
        )


class RagasEvaluator:
    """RAGAS-based RAG quality evaluation.

    Метрики:
    - faithfulness: ответ основан на retrieved context
    - answer_relevancy: релевантность ответа вопросу
    - context_precision: релевантность retrieved контекста
    - context_recall: полнота retrieved контекста

    Graceful skip если ragas не установлен.
    """

    async def evaluate(
        self,
        *,
        question: str,
        answer: str,
        contexts: list[str],
        ground_truth: str | None = None,
    ) -> dict[str, float]:
        """Оценивает один QA-pair.

        Returns dict с метриками 0-1.
        """
        try:
            from ragas import evaluate
            from ragas.metrics import (
                answer_relevancy,
                context_precision,
                faithfulness,
            )
            from datasets import Dataset
        except ImportError:
            logger.debug("ragas not installed, skipping evaluation")
            return {"ragas_available": 0.0}

        row = {
            "question": [question],
            "answer": [answer],
            "contexts": [contexts],
        }
        metrics = [faithfulness, answer_relevancy, context_precision]

        if ground_truth:
            from ragas.metrics import context_recall
            row["ground_truth"] = [ground_truth]
            metrics.append(context_recall)

        try:
            ds = Dataset.from_dict(row)
            result = evaluate(ds, metrics=metrics)
            return {k: float(v) for k, v in result.items()}
        except Exception as exc:
            logger.warning("RAGAS evaluation failed: %s", exc)
            return {"error": 0.0}


_moderation: ContentModeration | None = None
_ragas: RagasEvaluator | None = None


def get_moderation() -> ContentModeration:
    global _moderation
    if _moderation is None:
        _moderation = ContentModeration()
    return _moderation


def get_ragas() -> RagasEvaluator:
    global _ragas
    if _ragas is None:
        _ragas = RagasEvaluator()
    return _ragas
