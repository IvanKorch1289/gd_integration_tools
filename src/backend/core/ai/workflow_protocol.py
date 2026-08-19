"""Protocol-фасад для workflow registry/descriptor (cycle-5/D-AUDIT-501).

Назначение
----------
Убирает прямой импорт ``src.backend.infrastructure.workflow.registry``
из ``src.backend.dsl.agents.fastmcp_server`` (P1-слой violation в
DSL). DSL-слой зависит ТОЛЬКО от структурного :class:`Protocol`,
а конкретная реализация подгружается ленивым импортом на use-site.

Pattern
-------
* :class:`WorkflowDescriptorProtocol` — структурный протокол с полями
  dataclass-дескриптора (имя, описание, теги, схемы входа/выхода).
* :class:`WorkflowRegistryProtocol` — структурный протокол реестра
  (метод :meth:`list_all`).

Использование::

    # В DSL-слое (было: прямой импорт infrastructure.workflow.registry)
    from typing import TYPE_CHECKING
    if TYPE_CHECKING:
        from src.backend.core.ai.workflow_protocol import (
            WorkflowDescriptorProtocol,
            WorkflowRegistryProtocol,
        )

    # На use-site — ленивый импорт конкретной реализации
    def _register_prompts() -> None:
        from src.backend.infrastructure.workflow.registry import workflow_registry
        for wf in workflow_registry.list_all(): ...

Это согласуется с AGENTS.md правилами DSL-слоя: декларативные Protocol'ы
из core/ вместо прямой зависимости от infrastructure/.
"""

from __future__ import annotations

from typing import Any, Protocol

__all__ = ("WorkflowDescriptorProtocol", "WorkflowRegistryProtocol")


class WorkflowDescriptorProtocol(Protocol):
    """Структурный протокол метаданных durable workflow.

    Attributes:
        name: Уникальное логическое имя workflow (``orders.skb_flow``).
        description: Краткое человекочитаемое описание.
        input_schema: Pydantic-модель входного payload (или ``None``).
        output_schema: Pydantic-модель ожидаемого результата (или ``None``).
        max_attempts: Верхний предел retry-budget'а.
        tags: Кортеж произвольных тегов для каталога.

    """

    name: str
    description: str
    input_schema: Any
    output_schema: Any
    max_attempts: int
    tags: tuple[str, ...]


class WorkflowRegistryProtocol(Protocol):
    """Структурный протокол реестра workflow-дескрипторов.

    Methods:
        list_all: Возвращает детерминированно отсортированный список
            всех зарегистрированных descriptor'ов.

    """

    def list_all(self) -> list[WorkflowDescriptorProtocol]:
        """Вернуть список всех дескрипторов (sorted by name)."""
        ...
