"""S128 W2 — DSL-процессор Transform CDC Event: нормализация + фильтрация CDC payload.

Используется в pipeline ПОСЛЕ :class:`CDCCaptureProcessor` для приведения
событий к каноническому виду перед enrich / publish. До этого шага
паттерн был встроен в blueprint как inline ``transform`` step
(см. ``dsl/blueprints/cdc_enrich.yaml`` step 1+3). Выделение в отдельный
processor даёт:

* единый контракт ``operation/table/timestamp/old/new`` (camelCase в JSON
  ↔ snake_case в Python — оба принимаются на входе);
* декларативные фильтры ``operations=["INSERT", "UPDATE"]``;
* проекция полей ``project=["id", "table", "operation"]``;
* timestamp canonicalisation (``"2026-04-19T12:00:00"`` ↔
  :class:`datetime`);

Контракт DSL::

    .cdc_transform(
        operations=["INSERT", "UPDATE"],
        project=["id", "table", "operation"],
        include_old=False,
    )
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

from src.backend.core.logging import get_logger
from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor, handle_processor_error

__all__ = ("TransformCdcEventProcessor",)

_logger = get_logger("dsl.cdc.transform")

# Operation alias map: "insert" / "INSERT" / "I" → "INSERT"
_OPERATION_ALIASES: dict[str, str] = {
    "i": "INSERT",
    "insert": "INSERT",
    "u": "UPDATE",
    "update": "UPDATE",
    "d": "DELETE",
    "delete": "DELETE",
    "upsert": "UPSERT",
}


def _normalize_operation(raw: str) -> str:
    """Нормализует operation в UPPERCASE; возвращает ``"UNKNOWN"`` если не распознано."""
    if not raw:
        return "UNKNOWN"
    return _OPERATION_ALIASES.get(raw.strip().lower(), raw.strip().upper())


def _normalize_timestamp(raw: Any) -> str:
    """Приводит timestamp к ISO-8601 строке; ``str(raw)`` если не парсится."""
    if raw is None:
        return ""
    if isinstance(raw, datetime):
        return raw.isoformat()
    if isinstance(raw, str):
        return raw
    return str(raw)


class TransformCdcEventProcessor(BaseProcessor):
    """Нормализация + фильтрация + проекция CDC-событий.

    Args:
        operations: Список допустимых операций (``["INSERT", "UPDATE"]``).
            Регистронезависимо. ``None`` = все операции проходят.
        project: Список полей для проекции (``["id", "table", "operation"]``).
            ``None`` = все поля сохраняются (с учётом ``include_*``).
        include_old: Включать ``old`` payload (default ``True``).
        include_new: Включать ``new`` payload (default ``True``).
        timestamp_field: Имя поля timestamp в результате (default ``"timestamp"``).
        drop_unknown: Удалять события без ``operation`` или ``table`` (default ``True``).

    Пример::

        builder.from_cdc_capture("orders.changes", "oracle_prod", ["orders"]) \\
            .cdc_transform(operations=["INSERT", "UPDATE"], project=["id", "table"]) \\
            .dispatch_action("analytics.process_changes")
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.PURE

    def __init__(
        self,
        *,
        operations: list[str] | None = None,
        project: list[str] | None = None,
        include_old: bool = True,
        include_new: bool = True,
        timestamp_field: str = "timestamp",
        drop_unknown: bool = True,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "cdc_transform")
        self._operations_filter: set[str] | None = (
            {_normalize_operation(op) for op in operations} if operations else None
        )
        self._project = project
        self._include_old = include_old
        self._include_new = include_new
        self._timestamp_field = timestamp_field
        self._drop_unknown = drop_unknown

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Трансформирует CDC-события: нормализует операции, фильтрует и проецирует поля.

        Args:
            exchange: Текущий обмен с CDC-событиями (или одиночным событием).
            context: Контекст выполнения процессора.
        """
        body = exchange.in_message.body
        if body is None:
            return
        events = body if isinstance(body, list) else [body]

        normalized: list[dict[str, Any]] = []
        for ev in events:
            if not isinstance(ev, dict):
                _logger.debug("cdc_transform: skip non-dict event: %r", ev)
                continue
            op = _normalize_operation(ev.get("operation", ""))
            table = ev.get("table") or ev.get("source") or ""
            if self._drop_unknown and (not op or op == "UNKNOWN" or not table):
                _logger.debug("cdc_transform: drop unknown event: %r", ev)
                continue
            if self._operations_filter and op not in self._operations_filter:
                continue
            out = self._shape_event(ev, op, table)
            normalized.append(out)

        exchange.in_message.body = normalized
        _logger.debug(
            "cdc_transform: %d → %d events (filter=%s, project=%s)",
            len(events),
            len(normalized),
            self._operations_filter,
            self._project,
        )

    def _shape_event(self, ev: dict[str, Any], op: str, table: str) -> dict[str, Any]:
        """Применяет проекцию + include_* правила к одному событию."""
        if self._project:
            result: dict[str, Any] = {}
            for field in self._project:
                if field == "operation":
                    result[field] = op
                elif field == "table":
                    result[field] = table
                elif field in ("timestamp", "ts", "time"):
                    result[field] = _normalize_timestamp(
                        ev.get(self._timestamp_field) or ev.get(field)
                    )
                else:
                    # Top-level → fallback в new/old payloads
                    value = ev.get(field)
                    if value is None:
                        for container_key in ("new", "old"):
                            container = ev.get(container_key)
                            if isinstance(container, dict) and field in container:
                                value = container[field]
                                break
                    result[field] = value
            return result

        # Full mode: нормализуем ключи, применяем include_*
        result = {
            "operation": op,
            "table": table,
            self._timestamp_field: _normalize_timestamp(
                ev.get(self._timestamp_field) or ev.get("timestamp") or ev.get("ts")
            ),
        }
        if self._include_old and "old" in ev:
            result["old"] = ev["old"]
        if self._include_new and "new" in ev:
            result["new"] = ev["new"]
        for k, v in ev.items():
            if k in result or k in {
                "operation",
                "table",
                "old",
                "new",
                "timestamp",
                "ts",
            }:
                continue
            result[k] = v
        return result

    def to_spec(self) -> dict[str, Any]:
        """YAML-spec round-trip."""
        spec: dict[str, Any] = {
            "operations": (
                sorted(self._operations_filter) if self._operations_filter else None
            ),
            "project": self._project,
            "include_old": self._include_old,
            "include_new": self._include_new,
            "timestamp_field": self._timestamp_field,
            "drop_unknown": self._drop_unknown,
        }
        return {"cdc_transform": {k: v for k, v in spec.items() if v is not None}}
