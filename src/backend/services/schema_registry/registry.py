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

Production Hardening (Schema Registry V2):
    * JSON-Schema validation on register (opt-in via ``strict_validation``).
    * Metrics integration via :class:`MetricsRegistry`.
    * Snapshot persistence (``to_snapshot`` / ``from_snapshot``).
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.infrastructure.observability.metrics_registry import MetricsRegistry

__all__ = ("SchemaEntry", "SchemaKind", "ServiceSchemaRegistry", "get_schema_registry")

logger = logging.getLogger(__name__)


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

    Args:
        strict_validation: Если ``True`` — отклонять невалидные JSON-Schema
            при :meth:`register` (поднимает ``ValueError``).
        metrics: Опциональный :class:`MetricsRegistry` для счётчиков
            операций реестра.
    """

    __slots__ = ("_by_kind", "_strict_validation", "_metrics")

    def __init__(
        self,
        *,
        strict_validation: bool = False,
        metrics: MetricsRegistry | None = None,
    ) -> None:
        self._by_kind: dict[SchemaKind, dict[str, SchemaEntry]] = {
            kind: {} for kind in SchemaKind
        }
        self._strict_validation = strict_validation
        self._metrics = metrics

    # ── public CRUD ──────────────────────────────────────────────────

    def register(self, entry: SchemaEntry) -> SchemaEntry:
        """Регистрирует новую запись или перезаписывает существующую.

        Идемпотентно: повторная регистрация обновляет content. Конфликты
        не вызывают исключений — schema_registry это аналитический каталог,
        а не authoritative source (ProcessorRegistry).

        Raises:
            ValueError: Если ``strict_validation=True`` и схема невалидна.
        """
        if self._strict_validation:
            self._validate_entry(entry)

        self._by_kind[entry.kind][entry.name] = entry

        if self._metrics is not None:
            try:
                self._metrics.counter(
                    "schema_registry_register_total",
                    "Total schema registrations",
                    labels=("kind",),
                ).labels(kind=entry.kind.value).inc()
            except Exception:  # pragma: no cover - metrics best-effort
                pass

        return entry

    def get(self, kind: SchemaKind, name: str) -> SchemaEntry | None:
        """Возвращает запись по типу и имени; ``None`` если не найдена."""
        result = self._by_kind[kind].get(name)

        if self._metrics is not None:
            try:
                self._metrics.counter(
                    "schema_registry_get_total",
                    "Total schema lookups",
                    labels=("kind", "hit"),
                ).labels(kind=kind.value, hit="true" if result is not None else "false").inc()
            except Exception:  # pragma: no cover - metrics best-effort
                pass

        return result

    def list_kind(self, kind: SchemaKind) -> list[SchemaEntry]:
        """Возвращает все записи указанного типа (отсортированы по name).

        Снимает snapshot ключей через ``list(...)`` для безопасной
        итерации даже при конкурентной перезаписи.
        """
        bucket = self._by_kind[kind]
        names = sorted(list(bucket.keys()))
        result = [bucket[n] for n in names if n in bucket]

        if self._metrics is not None:
            try:
                self._metrics.counter(
                    "schema_registry_list_total",
                    "Total schema list queries",
                    labels=("kind",),
                ).labels(kind=kind.value).inc()
            except Exception:  # pragma: no cover - metrics best-effort
                pass

        return result

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

        if self._metrics is not None:
            try:
                self._metrics.counter(
                    "schema_registry_clear_total",
                    "Total schema registry clears",
                    labels=("scope",),
                ).labels(scope="all" if kind is None else kind.value).inc()
            except Exception:  # pragma: no cover - metrics best-effort
                pass

    # ── snapshot persistence ─────────────────────────────────────────

    def to_snapshot(self) -> dict[str, Any]:
        """Сериализует реестр в plain-dict snapshot.

        Returns:
            Словарь ``{"version": "2.0", "entries": [{...}]}`` для
            последующего восстановления через :meth:`from_snapshot`.
        """
        entries: list[dict[str, Any]] = []
        for kind in SchemaKind:
            for entry in self.list_kind(kind):
                entries.append({
                    "kind": entry.kind.value,
                    "name": entry.name,
                    "spec_schema": entry.spec_schema,
                    "output_schema": entry.output_schema,
                    "meta": dict(entry.meta),
                })
        return {"version": "2.0", "entries": entries}

    def from_snapshot(self, data: dict[str, Any]) -> None:
        """Восстанавливает реестр из snapshot (идемпотентно).

        Существующие записи перезаписываются; отсутствующие в snapshot
        остаются нетронутыми. Для полной очистки вызовите :meth:`clear`
        перед восстановлением.
        """
        if data.get("version") != "2.0":
            raise ValueError(f"Unsupported snapshot version: {data.get('version')!r}")

        for raw in data.get("entries", []):
            kind = SchemaKind(raw["kind"])
            entry = SchemaEntry(
                kind=kind,
                name=raw["name"],
                spec_schema=raw.get("spec_schema"),
                output_schema=raw.get("output_schema"),
                meta=raw.get("meta") or {},
            )
            self.register(entry)

    # ── private ──────────────────────────────────────────────────────

    def _validate_entry(self, entry: SchemaEntry) -> None:
        """Проверяет spec_schema / output_schema через jsonschema."""
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            logger.warning("jsonschema not available; skipping schema validation")
            return

        for field_name, schema in (
            ("spec_schema", entry.spec_schema),
            ("output_schema", entry.output_schema),
        ):
            if schema is None:
                continue
            try:
                Draft202012Validator.check_schema(schema)
            except Exception as exc:
                msg = f"Invalid JSON-Schema for {entry.kind.value}/{entry.name} {field_name}: {exc}"
                logger.warning(msg)
                raise ValueError(msg) from exc


_REGISTRY: ServiceSchemaRegistry = ServiceSchemaRegistry()


def get_schema_registry() -> ServiceSchemaRegistry:
    """Возвращает global-singleton :class:`ServiceSchemaRegistry`.

    Singleton используется как простой default для admin endpoint и
    docs-генерации; в lifespan можно создать локальный экземпляр и
    положить в ``app.state`` через ``app_state_singleton(factory=)``.
    """
    return _REGISTRY
