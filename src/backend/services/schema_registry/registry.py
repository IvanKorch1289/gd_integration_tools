"""``ServiceSchemaRegistry`` — runtime-каталог схем (R1, Step 6).

Хранит JSON-Schema артефакты по типам ``SchemaKind``: route / workflow /
service / plugin / processor / action.

В отличие от :class:`ProcessorRegistry` (живёт в ``dsl/registry``,
хранит зарегистрированные процессоры) этот реестр консолидирует все
JSON-Schema метаданные DSL для экспорта в LSP/OpenAPI/AsyncAPI/docs.

Заполняется на lifespan startup через :mod:`populator` после загрузки
плагинов и DSL-маршрутов.

Конкурентность (Sprint 16 К2 W1, DoD-2):
    Реестр работает по принципу single-writer/many-reader. Запись
    выполняется один раз в стартовой фазе lifespan (populator + register
    из плагинов), после чего runtime использует только чтения.

    Поэтому реализация lock-free: single-statement операции над
    ``dict`` атомарны под CPython GIL, что покрывает register/get/
    summary. ``list_kind`` снимает snapshot ключей перед итерацией, чтобы
    избежать ``RuntimeError: dictionary changed size during iteration`` в
    редких сценариях горячего перезаполнения. ``clear`` заменяет вложенные
    dict-ы целиком атомарной переустановкой ссылки.

    Прежний :class:`threading.RLock` создавал deadlock-риск в async-
    контексте (см. PLAN.md V22, GAP-таблица); замена ослабляет API до
    sync, что устраняет потребность в Lock и сохраняет совместимость
    со всеми существующими callsites (populator, exporters, event_bus,
    admin endpoints).
"""

from __future__ import annotations

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
    """Lock-free каталог схем (Sprint 16 К2 W1).

    See module docstring для деталей конкурентности и DoD-2.
    """

    __slots__ = ("_by_kind",)

    def __init__(self) -> None:
        self._by_kind: dict[SchemaKind, dict[str, SchemaEntry]] = {
            kind: {} for kind in SchemaKind
        }

    def register(self, entry: SchemaEntry) -> SchemaEntry:
        """Регистрирует новую запись или перезаписывает существующую.

        Идемпотентно: повторная регистрация обновляет content. Конфликты
        не вызывают исключений — schema_registry это аналитический каталог,
        а не authoritative source (ProcessorRegistry).
        """
        self._by_kind[entry.kind][entry.name] = entry
        return entry

    def get(self, kind: SchemaKind, name: str) -> SchemaEntry | None:
        """Возвращает запись по типу и имени; ``None`` если не найдена."""
        return self._by_kind[kind].get(name)

    def list_kind(self, kind: SchemaKind) -> list[SchemaEntry]:
        """Возвращает все записи указанного типа (отсортированы по name).

        Снимает snapshot ключей через ``list(...)`` для безопасной
        итерации даже при конкурентной перезаписи.
        """
        bucket = self._by_kind[kind]
        names = sorted(list(bucket.keys()))
        return [bucket[n] for n in names if n in bucket]

    def summary(self) -> dict[str, int]:
        """Сводка ``{kind: count}`` для admin/health-инвентаря."""
        return {kind.value: len(self._by_kind[kind]) for kind in SchemaKind}

    def clear(self, *, kind: SchemaKind | None = None) -> None:
        """Очищает реестр (полностью или только указанный kind).

        Использует атомарную переустановку ссылки на вложенный dict,
        чтобы конкурентные read-операции получали либо старый snapshot,
        либо пустой — без частично-очищенного состояния.
        """
        if kind is None:
            self._by_kind = {k: {} for k in SchemaKind}
        else:
            self._by_kind[kind] = {}


_REGISTRY: ServiceSchemaRegistry = ServiceSchemaRegistry()


def get_schema_registry() -> ServiceSchemaRegistry:
    """Возвращает global-singleton :class:`ServiceSchemaRegistry`.

    Singleton используется как простой default для admin endpoint и
    docs-генерации; в lifespan можно создать локальный экземпляр и
    положить в ``app.state`` через ``app_state_singleton(factory=)``.
    """
    return _REGISTRY
