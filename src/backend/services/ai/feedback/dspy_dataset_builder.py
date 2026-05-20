"""DSPy dataset builder из labeled-feedback (Sprint 11 K4 W5).

Берёт labeled feedback из :class:`AIFeedbackService` и строит DSPy-
совместимый dataset (``list[dspy.Example]``). DSPy импортируется лениво
для work в окружениях без [ai] extras.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

__all__ = ("DSPyDatasetBuilder", "DSPyExampleRecord")

logger = logging.getLogger("services.ai.feedback.dspy_dataset")


@dataclass(frozen=True, slots=True)
class DSPyExampleRecord:
    """Один пример для DSPy training-loop.

    Attributes:
        prompt: Вход модели (user_message + context).
        completion: Эталонный ответ (labeled).
        label: ``positive``/``negative`` для bootstrap-фильтрации.
        metadata: tenant_id, session_id, source feedback_id.
    """

    prompt: str
    completion: str
    label: str
    metadata: dict[str, Any]


class DSPyDatasetBuilder:
    """Build training dataset из labeled-feedback.

    Args:
        feedback_service: :class:`AIFeedbackService` instance.
    """

    def __init__(self, feedback_service: Any) -> None:
        self._service = feedback_service

    async def build(
        self,
        *,
        tenant_id: str | None = None,
        limit: int = 1000,
        only_positive: bool = False,
    ) -> list[DSPyExampleRecord]:
        """Собрать примеры из labeled feedback.

        Args:
            tenant_id: Опционально, ограничить tenant'ом.
            limit: Максимум записей.
            only_positive: Если True — только feedback с label=positive.

        Returns:
            List of :class:`DSPyExampleRecord`.
        """
        labeled = await self._service.list_labeled(
            tenant_id=tenant_id, limit=limit
        )
        out: list[DSPyExampleRecord] = []
        for item in labeled:
            label = str(getattr(item, "label", "") or item.get("label", ""))
            if only_positive and label != "positive":
                continue
            prompt = str(
                getattr(item, "prompt", None) or item.get("prompt", "") or ""
            )
            completion = str(
                getattr(item, "expected_answer", None)
                or item.get("expected_answer", "")
                or ""
            )
            if not prompt or not completion:
                continue
            out.append(
                DSPyExampleRecord(
                    prompt=prompt,
                    completion=completion,
                    label=label or "unknown",
                    metadata={
                        "tenant_id": getattr(
                            item, "tenant_id", item.get("tenant_id", "")
                        ),
                        "feedback_id": str(
                            getattr(item, "id", item.get("id", ""))
                        ),
                    },
                )
            )
        return out

    def to_dspy_examples(self, records: list[DSPyExampleRecord]) -> list[Any]:
        """Конвертация в ``dspy.Example`` (lazy-import).

        При отсутствии dspy-ai возвращает sentinel-dict с теми же полями —
        тесты могут работать без [ai] extra.
        """
        try:
            import dspy  # type: ignore[import-not-found]
        except ImportError:
            logger.info("dspy-ai not installed — returning dict examples")
            return [
                {"prompt": r.prompt, "completion": r.completion, "label": r.label}
                for r in records
            ]

        return [
            dspy.Example(prompt=r.prompt, completion=r.completion).with_inputs("prompt")
            for r in records
        ]
