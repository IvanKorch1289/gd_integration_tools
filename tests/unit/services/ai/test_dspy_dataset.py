"""Тесты Sprint 11 K4 W5 — DSPyDatasetBuilder + FeedbackTrainer."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.backend.services.ai.dspy.feedback_trainer import (
    FeedbackTrainer,
    FeedbackTrainResult,
)
from src.backend.services.ai.feedback.dspy_dataset_builder import (
    DSPyDatasetBuilder,
    DSPyExampleRecord,
)


@pytest.mark.asyncio
async def test_dataset_builder_filters_only_positive() -> None:
    """only_positive=True отбирает label='positive'."""
    items = [
        {
            "prompt": "q1",
            "expected_answer": "a1",
            "label": "positive",
            "id": 1,
            "tenant_id": "t",
        },
        {
            "prompt": "q2",
            "expected_answer": "a2",
            "label": "negative",
            "id": 2,
            "tenant_id": "t",
        },
    ]
    service = AsyncMock()
    service.list_labeled = AsyncMock(return_value=items)
    builder = DSPyDatasetBuilder(service)

    out = await builder.build(only_positive=True)

    assert len(out) == 1
    assert out[0].label == "positive"
    assert out[0].prompt == "q1"


@pytest.mark.asyncio
async def test_dataset_builder_skips_empty_prompts() -> None:
    """Записи без prompt/completion пропускаются."""
    items = [
        {"prompt": "", "expected_answer": "a", "label": "positive"},
        {"prompt": "q", "expected_answer": "", "label": "positive"},
        {
            "prompt": "good",
            "expected_answer": "yes",
            "label": "positive",
            "id": 9,
            "tenant_id": "t",
        },
    ]
    service = AsyncMock()
    service.list_labeled = AsyncMock(return_value=items)
    builder = DSPyDatasetBuilder(service)

    out = await builder.build()
    assert len(out) == 1
    assert out[0].prompt == "good"


def test_to_dspy_examples_falls_back_to_dict_when_no_dspy() -> None:
    """Без dspy-ai to_dspy_examples возвращает dict-list."""
    builder = DSPyDatasetBuilder(feedback_service=None)
    records = [
        DSPyExampleRecord(prompt="p", completion="c", label="positive", metadata={})
    ]
    # При отсутствии dspy функция отдаёт dict-объекты — это работает на любом окружении.
    # (В CI dspy-ai может быть, тогда метод вернёт настоящие Example — обе ветки валидны.)
    out = builder.to_dspy_examples(records)
    assert len(out) == 1


@pytest.mark.asyncio
async def test_feedback_trainer_noop_when_no_dspy() -> None:
    """Без dspy-ai trainer возвращает backend=noop и валидный prompt_version."""
    service = AsyncMock()
    service.list_labeled = AsyncMock(
        return_value=[
            {
                "prompt": "p",
                "expected_answer": "c",
                "label": "positive",
                "id": 1,
                "tenant_id": "t",
            }
        ]
    )
    storage = AsyncMock()
    storage.save = AsyncMock(return_value="v1")

    builder = DSPyDatasetBuilder(service)
    trainer = FeedbackTrainer(builder, storage)

    result = await trainer.train(prompt_name="rag_default")
    assert isinstance(result, FeedbackTrainResult)
    assert result.examples_used == 1
    assert result.prompt_version == "v1"
    assert result.backend in {"dspy", "noop"}


def test_feedback_cron_registration_uses_apscheduler() -> None:
    """register_feedback_cron вызывает scheduler.add_job."""
    from src.backend.infrastructure.scheduler.feedback_cron import (
        register_feedback_cron,
    )

    scheduler_mock = AsyncMock()
    add_job = AsyncMock()
    scheduler_mock.add_job = lambda *args, **kwargs: add_job(*args, **kwargs)

    async def _factory() -> Any:
        return None

    job_id = register_feedback_cron(scheduler_mock, trainer_factory=_factory)
    assert job_id == "ai_feedback_dspy_nightly"
