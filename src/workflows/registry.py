"""Реестр зарегистрированных durable workflows (IL-WF1.5).

Thin in-memory registry ``WorkflowDescriptor`` объектов — описаний
durable workflow'ов (логическое имя, input/output-схемы, лимиты
retry, теги и прочая метаинформация). Хранит также соответствие
``workflow_name → route_id`` (DSL-маршрут, под которым выполняется
workflow-логика).

Назначение:
    * Admin API (``/api/v1/admin/workflows/trigger/{workflow_name}``)
      ищет descriptor + route_id по имени и создаёт инстанс через
      :class:`WorkflowInstanceStore`.
    * MCP auto-export (``src/entrypoints/mcp/workflow_tools.py``)
      итерирует зарегистрированные workflows и регистрирует их как
      MCP tools с правильной JSON-схемой входа.
    * WorkflowBuilder (IL-WF1.3) после ``.build()`` вызовет
      ``workflow_registry.register(descriptor, route_id=...)``.

Реестр — thread-safe in-memory dict. Заменять на persistent storage
пока не нужно: перезагрузка spec происходит при рестарте процесса
(IL-WF1.3 плюс hot-reload — отдельная фаза).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pydantic import BaseModel

__all__ = (
    "WorkflowDescriptor",
    "WorkflowRegistry",
    "workflow_registry",
)


@dataclass(slots=True)
class WorkflowDescriptor:
    """Метаинформация об одном durable workflow.

    Attributes:
        name: Уникальное логическое имя workflow (``orders.skb_flow``).
            Используется как ключ в реестре и в UI/MCP tool name.
        description: Короткое человекочитаемое описание (одна фраза).
            Попадает в MCP tool description и в Admin API responses.
        input_schema: Pydantic-модель входного payload'а. ``None``
            означает "любой dict" — в MCP tool будет generic
            ``payload: dict`` без JSON-Schema валидации.
        output_schema: Pydantic-модель ожидаемого результата. ``None``
            допустимо, MCP tool просто вернёт raw dict.
        max_attempts: Верхний предел retry-budget'а для всего
            workflow'а (дублирует значение, жёстко прошитое в
            step-executor IL-WF1.3; хранится для видимости в UI).
        tags: Произвольные теги ("banking", "ai", "saga", ...). Не
            влияют на runtime, используются только для фильтрации в
            каталоге workflows.
    """

    name: str
    description: str = ""
    input_schema: type["BaseModel"] | None = None
    output_schema: type["BaseModel"] | None = None
    max_attempts: int = 10
    tags: tuple[str, ...] = field(default_factory=tuple)


class WorkflowRegistry:
    """In-memory реестр ``WorkflowDescriptor`` объектов.

    Thread-safe через :class:`threading.Lock` (регистрация происходит
    в startup, lookup — в hot-path, lock нужен для безопасной записи
    в случае ленивой подгрузки).

    Внутреннее состояние — два dict'а (descriptor по имени и
    ``workflow_name → route_id``) для O(1) lookup из обеих сторон.
    """

    def __init__(self) -> None:
        self._descriptors: dict[str, WorkflowDescriptor] = {}
        self._route_ids: dict[str, str] = {}
        self._lock = threading.Lock()

    def register(self, descriptor: WorkflowDescriptor, route_id: str) -> None:
        """Регистрирует workflow в реестре.

        Args:
            descriptor: Метаинформация workflow'а.
            route_id: DSL ``route_id`` — идентификатор pipeline-spec'а
                в :class:`RouteRegistry`, под которым выполняется
                workflow (в IL-WF1.3 это будет ``f"workflow:{name}"``).

        Raises:
            ValueError: Если workflow с таким именем уже зарегистрирован.
        """
        if not descriptor.name:
            raise ValueError("WorkflowDescriptor.name не может быть пустым")
        if not route_id:
            raise ValueError("route_id не может быть пустым")

        with self._lock:
            if descriptor.name in self._descriptors:
                raise ValueError(
                    f"Workflow '{descriptor.name}' уже зарегистрирован "
                    "(route_id=%s)" % self._route_ids.get(descriptor.name, "?"),
                )
            self._descriptors[descriptor.name] = descriptor
            self._route_ids[descriptor.name] = route_id

    def unregister(self, name: str) -> None:
        """Удаляет workflow из реестра (используется в hot-reload)."""
        with self._lock:
            self._descriptors.pop(name, None)
            self._route_ids.pop(name, None)

    def get(self, name: str) -> WorkflowDescriptor | None:
        """Возвращает descriptor по имени или ``None``."""
        return self._descriptors.get(name)

    def get_route_id(self, name: str) -> str | None:
        """Возвращает DSL ``route_id`` для workflow'а или ``None``."""
        return self._route_ids.get(name)

    def list_all(self) -> list[WorkflowDescriptor]:
        """Возвращает список всех зарегистрированных descriptor'ов.

        Порядок — детерминированный (сортировка по имени) — для
        предсказуемого вывода в UI / MCP tool catalog.
        """
        return [self._descriptors[name] for name in sorted(self._descriptors)]

    def clear(self) -> None:
        """Очищает реестр (используется в тестовых окружениях и
        при полном hot-reload spec'ов)."""
        with self._lock:
            self._descriptors.clear()
            self._route_ids.clear()

    def __contains__(self, name: str) -> bool:
        return name in self._descriptors

    def __len__(self) -> int:
        return len(self._descriptors)


# Глобальный singleton — импортируется из Admin API и MCP auto-export.
workflow_registry = WorkflowRegistry()
