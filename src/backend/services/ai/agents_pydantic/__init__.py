"""PydanticAI baseline (К4 MVP, Шаг 5).

Каркас typed-агентов поверх :class:`LiteLLMGateway`. Sprint 4/5 будет
наращивать tools/structured-output/RAG-tool. На MVP — base-класс и два
примера: ``EchoAgent`` и ``RagAnsweringAgent``.
"""

from src.backend.services.ai.agents_pydantic.base import (  # noqa: F401 — re-export
    BasePydanticAgent,
    PydanticAIUnavailable,
)

__all__ = ("BasePydanticAgent", "PydanticAIUnavailable")
