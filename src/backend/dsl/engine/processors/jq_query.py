"""DSL-процессор ``jq`` — фильтрация / трансформация через JMESPath-выражения.

Wave ``[wave:s5/k3-w1-processor-pack-1]``.

Использует библиотеку ``jmespath`` (из ``[core]`` deps). Lazy-import: если
библиотека не установлена, процессор fail-завершается с понятной ошибкой.

Контракт DSL (Camel-style Python)::

    .jq(expr="users[*].name", to="body.names")

YAML-форма::

    - jq:
        expr: "users[*].name"
        to: body.names

Feature flag: ``feature_flags.proc_jq`` (default-OFF).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.registry import processor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange


__all__ = ("JqProcessor",)


@processor(
    "jq",
    namespace="core",
    spec_schema={
        "type": "object",
        "properties": {
            "expr": {"type": "string"},
            "to": {"type": "string"},
            "mode": {"type": "string", "enum": ["all", "first", "scalar"]},
        },
        "required": ["expr"],
    },
    meta={"tier": 1, "category": "query"},
    tags=("jq", "query", "transform"),
)
class JqProcessor(BaseProcessor):
    """Применяет JMESPath-выражение к ``in_message.body``.

    Args:
        expr: JMESPath-выражение (``users[*].name``, ``foo.bar.baz``, etc.).
        to: Куда положить результат (``body.<field>`` / ``properties.<name>``).
        mode: ``all`` (default — list всех результатов), ``first`` (первый),
            ``scalar`` (одно значение, иначе None).
    """

    def __init__(
        self,
        expr: str,
        *,
        to: str = "body.jq_result",
        mode: str = "all",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"jq:{expr[:32]}")
        if not expr:
            raise ValueError("jq: expr must be non-empty")
        if mode not in {"all", "first", "scalar"}:
            raise ValueError(f"jq: mode must be 'all'|'first'|'scalar', got {mode!r}")
        self._expr = expr
        self._target = to
        self._mode = mode

    def _apply_target(self, exchange: "Exchange[Any]", value: Any) -> None:
        if self._target.startswith("body."):
            field = self._target[len("body.") :]
            body = exchange.in_message.body
            if not isinstance(body, dict):
                body = {}
                exchange.in_message.body = body  
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

            if not feature_flags.proc_jq:
                exchange.set_property("jq_status", "skipped")
                return
        except Exception as _:  # noqa: BLE001
            pass

        try:
            import jmespath  
        except ImportError as exc:
            exchange.fail(f"jq: jmespath not available: {exc}")
            return

        body = exchange.in_message.body
        try:
            results = jmespath.search(self._expr, body)
            if not isinstance(results, list):
                results = [results] if results is not None else []
        except Exception as exc:  # noqa: BLE001
            exchange.fail(f"jq evaluation error: {exc}")
            return

        match self._mode:
            case "all":
                value: Any = results
            case "first":
                value = results[0] if results else None
            case "scalar":
                value = results[0] if len(results) == 1 else None
            case _:
                value = results

        self._apply_target(exchange, value)

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {"expr": self._expr}
        if self._target != "body.jq_result":
            spec["to"] = self._target
        if self._mode != "all":
            spec["mode"] = self._mode
        return {"jq": spec}
