"""DSL-процессор ``regex_extractor`` — извлечение через регулярные выражения.

Wave ``[wave:s5/k3-w1-processor-pack-1]``.

Использует stdlib ``re`` (не требует extra-зависимостей). Поддерживает
именованные группы (``(?P<name>...)``), множественные находки и три режима
извлечения.

Контракт DSL (Camel-style Python)::

    .regex_extractor(
        pattern=r"order_(?P<id>\\d+)_(?P<status>\\w+)",
        source="body.text",
        to="body.parsed",
        mode="first_named",
    )

YAML-форма::

    - regex_extractor:
        pattern: "order_(?P<id>\\d+)_(?P<status>\\w+)"
        source: body.text
        to: body.parsed
        mode: first_named

Feature flag: ``feature_flags.proc_regex_extractor`` (default-OFF).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.registry import processor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange


__all__ = ("RegexExtractorProcessor",)


_ALLOWED_MODES = frozenset({"all", "first", "first_named", "all_named", "groups"})


@processor(
    "regex_extractor",
    namespace="core",
    spec_schema={
        "type": "object",
        "properties": {
            "pattern": {"type": "string"},
            "source": {"type": "string"},
            "to": {"type": "string"},
            "mode": {"type": "string", "enum": sorted(_ALLOWED_MODES)},
            "flags": {"type": "integer"},
        },
        "required": ["pattern"],
    },
    meta={"tier": 1, "category": "transform"},
    tags=("regex", "extract", "transform"),
)
class RegexExtractorProcessor(BaseProcessor):
    """Извлекает данные из текста через регулярное выражение.

    Args:
        pattern: Регулярное выражение (см. ``re``).
        source: Откуда читать текст (``body``, ``body.<field>``, ``properties.<name>``).
        to: Куда положить результат (``body.<field>`` / ``properties.<name>``).
        mode:
            * ``all`` — list всех findall();
            * ``first`` — первое findall() значение или None;
            * ``first_named`` — dict групп первого matcher (re.search);
            * ``all_named`` — list[dict] групп всех matcher'ов (re.finditer);
            * ``groups`` — tuple групп первого matcher.
        flags: Флаги ``re`` (e.g. ``re.IGNORECASE | re.MULTILINE``).
    """

    def __init__(
        self,
        pattern: str,
        *,
        source: str = "body",
        to: str = "body.regex_result",
        mode: str = "all",
        flags: int = 0,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"regex_extractor:{pattern[:32]}")
        if not pattern:
            raise ValueError("regex_extractor: pattern must be non-empty")
        if mode not in _ALLOWED_MODES:
            raise ValueError(
                f"regex_extractor: mode must be one of {sorted(_ALLOWED_MODES)}, "
                f"got {mode!r}"
            )
        self._pattern_source = pattern
        try:
            self._regex = re.compile(pattern, flags)
        except re.error as exc:
            raise ValueError(f"regex_extractor: invalid pattern: {exc}") from exc
        self._source = source
        self._target = to
        self._mode = mode
        self._flags = flags

    def _resolve_source(self, exchange: "Exchange[Any]") -> str:
        body = exchange.in_message.body
        if self._source == "body":
            return body if isinstance(body, str) else str(body)
        if self._source.startswith("body."):
            field = self._source[len("body.") :]
            value = body.get(field) if isinstance(body, dict) else None
            return value if isinstance(value, str) else str(value or "")
        if self._source.startswith("properties."):
            field = self._source[len("properties.") :]
            value = exchange.properties.get(field)
            return value if isinstance(value, str) else str(value or "")
        return ""

    def _apply_target(self, exchange: "Exchange[Any]", value: Any) -> None:
        if self._target.startswith("body."):
            field = self._target[len("body.") :]
            body = exchange.in_message.body
            if not isinstance(body, dict):
                body = {}
                exchange.in_message.body = body  # type: ignore[assignment]
            body[field] = value
            return
        if self._target.startswith("properties."):
            field = self._target[len("properties.") :]
            exchange.set_property(field, value)
            return
        exchange.set_property(self._target, value)

    async def process(
        self, exchange: "Exchange[Any]", context: "ExecutionContext"
    ) -> None:
        try:
            from src.backend.core.config.features import feature_flags

            if not feature_flags.proc_regex_extractor:
                exchange.set_property("regex_extractor_status", "skipped")
                return
        except Exception as _:  # noqa: BLE001
            pass

        text = self._resolve_source(exchange)
        match self._mode:
            case "all":
                result: Any = self._regex.findall(text)
            case "first":
                matches = self._regex.findall(text)
                result = matches[0] if matches else None
            case "first_named":
                m = self._regex.search(text)
                result = m.groupdict() if m else None
            case "all_named":
                result = [m.groupdict() for m in self._regex.finditer(text)]
            case "groups":
                m = self._regex.search(text)
                result = m.groups() if m else None
            case _:
                result = []

        self._apply_target(exchange, result)

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {"pattern": self._pattern_source}
        if self._source != "body":
            spec["source"] = self._source
        if self._target != "body.regex_result":
            spec["to"] = self._target
        if self._mode != "all":
            spec["mode"] = self._mode
        if self._flags:
            spec["flags"] = self._flags
        return {"regex_extractor": spec}
