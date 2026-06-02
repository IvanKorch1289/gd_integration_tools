"""EchoAgent — минимальный пример typed-агента (для smoke-tests)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from src.backend.services.ai.agents_pydantic.base import BasePydanticAgent

__all__ = ("EchoResult", "EchoAgent")


class EchoResult(BaseModel):
    """Эхо-ответ: содержит исходное сообщение и кол-во символов."""

    message: str = Field(description="Возвращённое сообщение")
    length: int = Field(ge=0, description="Длина исходного сообщения")


class EchoAgent(BasePydanticAgent[EchoResult]):
    """Простейший typed-агент. Полезен для тестов без сетевых вызовов."""

    result_type = EchoResult

    def __init__(self, **kwargs: object) -> None:
        super().__init__(
            system_prompt="Echo back the user's message and its length.",
            **kwargs,  
        )
