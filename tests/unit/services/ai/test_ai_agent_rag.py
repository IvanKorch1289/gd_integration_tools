# ruff: noqa: S101
"""Unit-тесты RAG-augmentation в ``AIAgentService.chat`` (Wave 13).

Проверяется поведение метода ``_maybe_augment_with_rag``:

* при ``rag_namespace=None`` — обогащение не выполняется;
* при ``rag_settings.enabled=False`` — обогащение пропущено даже с namespace;
* при включённом RAG — последний user-message подменяется на augmented;
* при ошибке в ``RAGService.augment_prompt`` — основной flow продолжается
  без обогащения (best-effort).

Тесты не поднимают реальный Qdrant / sentence-transformers — RAGService
мокается через ``_resolve_rag_service``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.backend.services.ai.ai_agent import AIAgentService


class _StubRag:
    """Лёгкий стаб RAGService — фиксирует вызовы augment_prompt."""

    def __init__(self, response: str, *, raises: Exception | None = None) -> None:
        self.response = response
        self.raises = raises
        self.calls: list[dict[str, Any]] = []

    async def augment_prompt(
        self, *, query: str, system_prompt: str, top_k: int, namespace: str | None
    ) -> str:
        self.calls.append(
            {
                "query": query,
                "system_prompt": system_prompt,
                "top_k": top_k,
                "namespace": namespace,
            }
        )
        if self.raises is not None:
            raise self.raises
        return self.response


@pytest.fixture
def agent() -> AIAgentService:
    """Свежий экземпляр сервиса (singleton нам не подходит для изоляции)."""
    return AIAgentService()


async def test_no_namespace_skips_augmentation(agent: AIAgentService) -> None:
    """Без ``rag_namespace`` augmentation не запускается, messages не меняются."""
    messages = [{"role": "user", "content": "Привет"}]
    used, result = await agent._maybe_augment_with_rag(
        messages=messages, namespace=None, top_k=None, system_prompt=""
    )
    assert used is False
    assert result is messages


async def test_disabled_rag_skips_augmentation(agent: AIAgentService) -> None:
    """При ``rag_settings.enabled=False`` augmentation пропускается."""
    messages = [{"role": "user", "content": "Привет"}]
    rag = _StubRag(response="ENRICHED")

    with (
        patch("src.backend.core.config.rag.rag_settings.enabled", False),
        patch.object(AIAgentService, "_resolve_rag_service", return_value=rag),
    ):
        used, result = await agent._maybe_augment_with_rag(
            messages=messages, namespace="notebooks", top_k=None, system_prompt=""
        )

    assert used is False
    assert result is messages
    assert rag.calls == []


async def test_enabled_rag_augments_last_user_message(agent: AIAgentService) -> None:
    """Включённый RAG подменяет последний user-message на augmented."""
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "первый"},
        {"role": "assistant", "content": "ответ"},
        {"role": "user", "content": "последний"},
    ]
    rag = _StubRag(response="AUGMENTED")

    with (
        patch("src.backend.core.config.rag.rag_settings.enabled", True),
        patch("src.backend.core.config.rag.rag_settings.top_k", 7),
        patch.object(AIAgentService, "_resolve_rag_service", return_value=rag),
    ):
        used, result = await agent._maybe_augment_with_rag(
            messages=messages, namespace="notebooks", top_k=None, system_prompt="SYS"
        )

    assert used is True
    # последний user-message подменён, остальные нетронуты
    assert result[-1]["content"] == "AUGMENTED"
    assert result[-1]["role"] == "user"
    assert result[0] == messages[0]
    assert result[1] == messages[1]
    assert result[2] == messages[2]
    # rag вызван корректно (top_k взят из rag_settings, query — последний user)
    assert rag.calls == [
        {
            "query": "последний",
            "system_prompt": "SYS",
            "top_k": 7,
            "namespace": "notebooks",
        }
    ]


async def test_explicit_top_k_overrides_settings(agent: AIAgentService) -> None:
    """Явно переданный ``top_k`` перекрывает значение из rag_settings."""
    messages = [{"role": "user", "content": "запрос"}]
    rag = _StubRag(response="X")

    with (
        patch("src.backend.core.config.rag.rag_settings.enabled", True),
        patch("src.backend.core.config.rag.rag_settings.top_k", 5),
        patch.object(AIAgentService, "_resolve_rag_service", return_value=rag),
    ):
        await agent._maybe_augment_with_rag(
            messages=messages, namespace="ns", top_k=2, system_prompt=""
        )

    assert rag.calls[0]["top_k"] == 2


async def test_augment_failure_falls_back_to_original(agent: AIAgentService) -> None:
    """Ошибка ``augment_prompt`` не прерывает chat — возвращаются исходные messages."""
    messages = [{"role": "user", "content": "запрос"}]
    rag = _StubRag(response="N/A", raises=RuntimeError("vector store down"))

    with (
        patch("src.backend.core.config.rag.rag_settings.enabled", True),
        patch.object(AIAgentService, "_resolve_rag_service", return_value=rag),
    ):
        used, result = await agent._maybe_augment_with_rag(
            messages=messages, namespace="ns", top_k=None, system_prompt=""
        )

    assert used is False
    assert result is messages


async def test_resolve_rag_service_returns_none_skips(agent: AIAgentService) -> None:
    """Если RAGService недоступен (None) — augmentation пропускается тихо."""
    messages = [{"role": "user", "content": "q"}]

    with (
        patch("src.backend.core.config.rag.rag_settings.enabled", True),
        patch.object(AIAgentService, "_resolve_rag_service", return_value=None),
    ):
        used, result = await agent._maybe_augment_with_rag(
            messages=messages, namespace="ns", top_k=None, system_prompt=""
        )

    assert used is False
    assert result is messages


async def test_chat_propagates_rag_flag_in_response(agent: AIAgentService) -> None:
    """``chat()`` отдаёт ``rag_used``/``rag_namespace`` в успешном ответе."""
    messages = [{"role": "user", "content": "вопрос"}]

    fake_provider_response = {
        "choices": [{"message": {"content": "LLM-ответ"}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 2},
    }

    rag = _StubRag(response="ENRICHED-Q")
    provider_mock = AsyncMock(return_value=fake_provider_response)

    with (
        patch("src.backend.core.config.rag.rag_settings.enabled", True),
        patch.object(AIAgentService, "_resolve_rag_service", return_value=rag),
        patch.dict(agent._providers, {"perplexity": provider_mock}),
        patch.object(agent, "_record_feedback", new=AsyncMock(return_value="fb-1")),
    ):
        result = await agent.chat(
            messages, model="m", provider="perplexity", rag_namespace="notebooks"
        )

    assert result["success"] is True
    assert result["content"] == "LLM-ответ"
    assert result["rag_used"] is True
    assert result["rag_namespace"] == "notebooks"
    # provider получил augmented-сообщение
    sent_messages = provider_mock.call_args.args[0]
    assert sent_messages[-1]["content"] == "ENRICHED-Q"


async def test_chat_without_rag_no_extra_keys(agent: AIAgentService) -> None:
    """Без ``rag_namespace`` ключи ``rag_used``/``rag_namespace`` отсутствуют."""
    messages = [{"role": "user", "content": "вопрос"}]
    fake_provider_response = {
        "choices": [{"message": {"content": "ответ"}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }
    provider_mock = AsyncMock(return_value=fake_provider_response)

    with (
        patch.dict(agent._providers, {"perplexity": provider_mock}),
        patch.object(agent, "_record_feedback", new=AsyncMock(return_value=None)),
    ):
        result = await agent.chat(messages, model="m", provider="perplexity")

    assert "rag_used" not in result
    assert "rag_namespace" not in result
