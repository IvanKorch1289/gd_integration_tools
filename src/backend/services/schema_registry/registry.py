"""``ServiceSchemaRegistry`` — runtime-каталог схем (R1, Step 6).

Хранит JSON-Schema артефакты по типам ``SchemaKind``: route / workflow /
service / plugin / processor / action.

В отличие от :class:`ProcessorRegistry` (живёт в ``dsl/registry``,
хранит зарегистрированные процессоры) этот реестр консолидирует все
JSON-Schema метаданные DSL для экспорта в LSP/OpenAPI/AsyncAPI/docs.

Заполняется на lifespan startup через :mod:`populator` после загрузки
плагинов и DSL-маршрутов.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

__all__ = ("SchemaEntry", "SchemaKind", "ServiceSchemaRegistry", "get_schema_registry")


class SchemaKind(StrEnum):
    """Тип артефакта, к которому привязана схема."""

    ROUTE = "route"
    WORKFLOW = "workflow"
    SERVICE = "service"
    PLUGIN = "plugin"
    PROCESSOR = "processor"
    ACTION = "action"
    EVENT = "event"
    """S13 K3 W3: схема payload'а для EventBus.publish() — registry-driven validation."""


@dataclass(frozen=True, slots=True)
class SchemaEntry:
    """Запись в каталоге схем.

    Атрибуты:
        kind: Тип артефакта (:class:`SchemaKind`).
        name: Уникальное имя артефакта (route_id, action_name, ...).
        spec_schema: JSON-Schema для входной спецификации (params/конфигурация).
        output_schema: JSON-Schema для выхода (опционально).
        meta: Произвольные метаданные (namespace, version, capabilities, ...).
    """

    kind: SchemaKind
    name: str
    spec_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    meta: dict[str, Any] = field(default_factory=dict)


class ServiceSchemaRegistry:
    """Thread-safe каталог схем (R1, V15 Sprint 1)."""

    def __init__(self) -> None:
        self._by_kind: dict[SchemaKind, dict[str, SchemaEntry]] = {
            kind: {} for kind in SchemaKind
        }
        self._lock = threading.RLock()

    def register(self, entry: SchemaEntry) -> SchemaEntry:
        """Регистрирует новую запись или перезаписывает существующую.

        Идемпотентно: повторная регистрация обновляет content. Конфликты
        не вызывают исключений — schema_registry это аналитический каталог,
        а не authoritative source (ProcessorRegistry).
        """
        with self._lock:
            self._by_kind[entry.kind][entry.name] = entry
            return entry

    def get(self, kind: SchemaKind, name: str) -> SchemaEntry | None:
        """Возвращает запись по типу и имени; ``None`` если не найдена."""
        with self._lock:
            return self._by_kind[kind].get(name)

    def list_kind(self, kind: SchemaKind) -> list[SchemaEntry]:
        """Возвращает все записи указанного типа (отсортированы по name)."""
        with self._lock:
            return [self._by_kind[kind][n] for n in sorted(self._by_kind[kind])]

    def summary(self) -> dict[str, int]:
        """Сводка ``{kind: count}`` для admin/health-инвентаря."""
        with self._lock:
            return {kind.value: len(self._by_kind[kind]) for kind in SchemaKind}

    def clear(self, *, kind: SchemaKind | None = None) -> None:
        """Очищает реестр (полностью или только указанный kind)."""
        with self._lock:
            if kind is None:
                for k in SchemaKind:
                    self._by_kind[k].clear()
            else:
                self._by_kind[kind].clear()


_REGISTRY: ServiceSchemaRegistry = ServiceSchemaRegistry()


def get_schema_registry() -> ServiceSchemaRegistry:
    """Возвращает global-singleton :class:`ServiceSchemaRegistry`.

    Singleton используется как простой default для admin endpoint и
    docs-генерации; в lifespan можно создать локальный экземпляр и
    положить в ``app.state`` через ``app_state_singleton(factory=)``.
    """
    return _REGISTRY
