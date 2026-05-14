"""DSL-процессор ``jq`` — фильтрация / трансформация через jq-выражения.

Wave ``[wave:s5/k3-w1-processor-pack-1]``.

Использует библиотеку ``pyjq`` (из ``[dsl-extras-2]``). Lazy-import: если
библиотека не установлена, процессор fail-завершается с понятной ошибкой.

Контракт DSL (Camel-style Python)::

    .jq(expr=".users | map(select(.age > 18)) | map(.name)", to="body.adults")

YAML-форма::

    - jq:
        expr: ".users | map(select(.age > 18)) | map(.name)"
        to: body.adults

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
    """Применяет jq-выражение к ``in_message.body``.

    Args:
        expr: jq-выражение (``.foo``, ``.[] | select(.a > 1)``, etc.).
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
            raise ValueError(
                f"jq: mode must be 'all'|'first'|'scalar', got {mode!r}"
            )
        self._expr = expr
        self._target = to
        self._mode = mode

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

            if not feature_flags.proc_jq:
                exchange.set_property("jq_status", "skipped")
                return
        except Exception:  # noqa: BLE001
            pass

        try:
            import pyjq  # type: ignore[import-not-found]
        except ImportError as exc:
            exchange.fail(f"jq: pyjq not available: {exc}")
            return

        body = exchange.in_message.body
        try:
            results = pyjq.all(self._expr, body)
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
