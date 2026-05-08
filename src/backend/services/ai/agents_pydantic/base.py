"""Базовый класс typed-агентов поверх PydanticAI + LiteLLMGateway."""

from __future__ import annotations

import logging
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

logger = logging.getLogger(__name__)

__all__ = ("BasePydanticAgent", "PydanticAIUnavailable", "ResultT")

ResultT = TypeVar("ResultT", bound=BaseModel)


class PydanticAIUnavailable(RuntimeError):
    """``pydantic_ai`` не установлен — добавьте extra '[ai-2026]'."""


class BasePydanticAgent(Generic[ResultT]):
    """Базовая обёртка над ``pydantic_ai.Agent`` с типизированным результатом.

    На MVP реализован тонкий fallback-режим: если ``pydantic_ai`` доступен,
    создаётся настоящий ``Agent`` через :class:`LiteLLMModel` adapter; иначе
    :meth:`run` поднимает :class:`PydanticAIUnavailable`. Sprint 4 уберёт
    fallback и привяжет structured-output (через ``instructor``).
    """

    result_type: type[BaseModel]

    def __init__(
        self,
        *,
        result_type: type[ResultT] | None = None,
        system_prompt: str = "",
        model_name: str | None = None,
        gateway: Any | None = None,
    ) -> None:
        if result_type is not None:
            self.result_type = result_type
        if not hasattr(self, "result_type"):
            raise TypeError(
                "BasePydanticAgent: укажите result_type=PydanticModel либо "
                "переопределите атрибут класса."
            )
        self._system_prompt = system_prompt
        self._model_name = model_name
        self._gateway = gateway
        self._agent: Any = None

    def _ensure_gateway(self) -> Any:
        if self._gateway is not None:
            return self._gateway
        from src.backend.services.ai.gateway.client import get_litellm_gateway

        self._gateway = get_litellm_gateway()
        return self._gateway

    def _ensure_agent(self) -> Any:
        if self._agent is not None:
            return self._agent
        try:
            from pydantic_ai import Agent  # type: ignore[import-not-found]
        except ImportError as exc:
            raise PydanticAIUnavailable(
                "pydantic-ai не установлен — добавьте extra '[ai-2026]'."
            ) from exc

        from src.backend.services.ai.agents_pydantic.adapter import LiteLLMModel

        gateway = self._ensure_gateway()
        model = LiteLLMModel(gateway=gateway, model_name=self._model_name)
        self._agent = Agent(
            model=model,
            result_type=self.result_type,
            system_prompt=self._system_prompt,
        )
        return self._agent

    async def run(self, user_input: str, **deps: Any) -> ResultT:
        """Запускает агента и возвращает строго-типизированный результат."""
        agent = self._ensure_agent()
        result = await agent.run(user_input, deps=deps if deps else None)
        data = getattr(result, "data", result)
        if isinstance(data, self.result_type):
            return data  # type: ignore[return-value]
        # PydanticAI возвращает уже валидированную модель; на всякий случай:
        return self.result_type.model_validate(data)  # type: ignore[return-value]
