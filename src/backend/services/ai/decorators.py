"""Sprint 14 K4 W1 — ``@ai_service`` decorator для plugin-AI-функций.

Назначение:
    Декоратор, который превращает обычную async-функцию плагина в
    зарегистрированный AI-сервис. При regestration:

    * проверяет ``capabilities`` через ``CapabilityGate`` (если предоставлен);
    * сохраняет signature/docstring в :class:`AIPluginRegistry`;
    * экспортирует функцию как handler для action-bus / RAG / agent-memory.

Использование:
    .. code-block:: python

        from src.backend.services.ai.decorators import ai_service

        @ai_service(
            name="credit.score.llm",
            model="gpt-4o-mini",
            capabilities=["ai.llm.openai", "secrets.read"],
        )
        async def score_application(application: dict) -> dict:
            \"\"\"Оценить заявку через LLM.\"\"\"
            ...

Изоляция от Sprint 11:
    Файл изолирован — не пересекается с ``services/ai/litellm_*.py`` или
    ``services/ai/rag_*.py``. Sprint 11 владеет LLM/RAG infrastructure,
    мы — только декоратор-API + registry.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from functools import wraps
from typing import Any, ParamSpec, TypeVar

from src.backend.core.logging import get_logger
from src.backend.services.ai.registry import AIPluginRegistry, get_ai_plugin_registry

__all__ = ("AIServiceSpec", "ai_service")

_logger = get_logger("services.ai.decorators")

_P = ParamSpec("_P")
_R = TypeVar("_R")


@dataclass(slots=True, frozen=True)
class AIServiceSpec:
    """Метаданные AI-сервиса для каталога/OpenAPI."""

    name: str
    model: str | None
    capabilities: tuple[str, ...]
    description: str
    function: Callable[..., Awaitable[Any]]
    signature_repr: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "model": self.model,
            "capabilities": list(self.capabilities),
            "description": self.description,
            "signature": self.signature_repr,
        }


def ai_service(
    *,
    name: str,
    model: str | None = None,
    capabilities: Iterable[str] = (),
    description: str | None = None,
    registry: AIPluginRegistry | None = None,
) -> Callable[[Callable[_P, Awaitable[_R]]], Callable[_P, Awaitable[_R]]]:
    """Декоратор регистрации AI-сервиса плагина.

    Args:
        name: Уникальный action-id (например ``"credit.score.llm"``).
        model: Опц. идентификатор LLM-модели для отчётности / cost dashboard.
        capabilities: Перечень capability-имён, которые сервис требует.
            Передаются в Capability Gate при первом вызове.
        description: Опц. человекочитаемое описание (для каталога).
        registry: Опц. явный :class:`AIPluginRegistry` — иначе используется
            глобальный singleton :func:`get_ai_plugin_registry`.

    Returns:
        Decorator, регистрирующий функцию и возвращающий её без модификации.

    Raises:
        ValueError: Если декорированная функция не async или ``name`` пуст.
    """
    if not name or not isinstance(name, str):
        raise ValueError("ai_service.name must be a non-empty string")

    caps_tuple = tuple(capabilities)

    def decorator(func: Callable[_P, Awaitable[_R]]) -> Callable[_P, Awaitable[_R]]:
        if not inspect.iscoroutinefunction(func):
            raise ValueError(
                f"@ai_service expects async function, got {func.__name__!r}"
            )

        spec = AIServiceSpec(
            name=name,
            model=model,
            capabilities=caps_tuple,
            description=description or (inspect.getdoc(func) or "").split("\n", 1)[0],
            function=func,
            signature_repr=str(inspect.signature(func)),
        )

        target_registry = registry or get_ai_plugin_registry()
        target_registry.register(spec)
        _logger.info(
            "ai_service registered: %s (model=%s, caps=%s)",
            spec.name,
            spec.model,
            spec.capabilities,
        )

        @wraps(func)
        async def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> _R:
            return await func(*args, **kwargs)

        return wrapper

    return decorator
