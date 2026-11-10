"""DI-провайдер реестра промптов (ADR-0437).

``PromptRegistry`` (services/ai) хранит версии промптов (fallback-режим) либо
читает их из Langfuse. До ADR-0437 реестр не был подключён к DI и не имел
HTTP-поверхности: портал не мог показать версии, активировать версию и
сравнивать A/B.
"""

from __future__ import annotations

from typing import Any

__all__ = ("get_prompt_registry_provider", "set_prompt_registry_provider")

_overrides: dict[str, Any] = {}


def get_prompt_registry_provider() -> Any:
    """Вернуть singleton :class:`PromptRegistry`.

    Returns:
        Экземпляр реестра промптов (или override из тестов).

    """
    if "prompt_registry" in _overrides:
        return _overrides["prompt_registry"]
    from src.backend.services.ai.prompt_registry import PromptRegistry

    registry = _overrides.get("prompt_registry_singleton")
    if registry is None:
        registry = PromptRegistry()
        _overrides["prompt_registry_singleton"] = registry
    return registry


def set_prompt_registry_provider(registry: Any) -> None:
    """Установить override реестра промптов (test-инжекция).

    Args:
        registry: Экземпляр реестра (или ``None`` — сброс).

    """
    if registry is None:
        _overrides.pop("prompt_registry", None)
        _overrides.pop("prompt_registry_singleton", None)
        return
    _overrides["prompt_registry"] = registry
