"""Реестр реализаций Protocol'ов — единая точка регистрации и поиска.

Каждый Protocol из :mod:`app.core.protocols` может иметь несколько реализаций
(например, :class:`LLMProvider` → Claude/Ollama/OpenAI). Реестр хранит
именованные инстансы и позволяет DI-контейнеру получать реализацию по имени,
заданному в конфиге.

Преимущества по сравнению с прямой импорт-зависимостью:

* бизнес-код использует ``Protocol``-тип в аннотации, не конкретный класс;
* подмена реализации в тестах/dev/prod — через конфиг, а не код;
* отсутствует циклическая импорт-зависимость.

Использование::

    from app.core.protocols import LLMProvider
    from app.core.providers_registry import get_provider

    llm: LLMProvider = get_provider("llm", "ollama")
    answer = await llm.chat([{"role": "user", "content": "hi"}])
"""

from __future__ import annotations

from typing import Any

__all__ = (
    "register_provider",
    "get_provider",
    "list_providers",
    "unregister_provider",
    "clear_registry",
)

_registry: dict[str, dict[str, Any]] = {}


def register_provider(category: str, name: str, instance: Any) -> None:
    """Регистрирует реализацию под именем в заданной категории.

    Args:
        category: Имя Protocol-категории (``"llm"``, ``"browser"``,
            ``"notifier"``, ``"exporter"``, ``"memory"``, ``"cdc"``,
            ``"soap"``, ``"prompt_store"``).
        name: Уникальное имя реализации в категории (``"ollama"``, ``"claude"``).
        instance: Объект-реализация, соответствующий Protocol категории.

    Идемпотентна — повторная регистрация перезаписывает предыдущее значение.
    """
    _registry.setdefault(category, {})[name] = instance


def get_provider(category: str, name: str) -> Any:
    """Возвращает зарегистрированную реализацию.

    Raises:
        KeyError: Если категория или имя не найдены.
    """
    if category not in _registry or name not in _registry[category]:
        raise KeyError(f"Provider '{name}' не зарегистрирован в категории '{category}'")
    return _registry[category][name]


def list_providers(category: str | None = None) -> dict[str, list[str]]:
    """Возвращает перечень зарегистрированных реализаций.

    Если ``category=None`` — возвращает все категории. Иначе только указанную.
    """
    if category is None:
        return {cat: sorted(items.keys()) for cat, items in _registry.items()}
    return {category: sorted(_registry.get(category, {}).keys())}


def unregister_provider(category: str, name: str) -> None:
    """Удаляет реализацию из реестра (тихо, если её нет)."""
    if category in _registry and name in _registry[category]:
        del _registry[category][name]


def clear_registry() -> None:
    """Полностью очищает реестр. Используется в тестах и при reload."""
    _registry.clear()
