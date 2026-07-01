"""DSL-процессор ``jsonpath`` — извлечение значений через JSONPath.

Wave ``[wave:s5/k3-w1-processor-pack-1]``.

Использует библиотеку ``jsonpath-ng`` (из ``[dsl-extras]``). Lazy-import:
если библиотека не установлена, процессор завершается с понятной ошибкой.

Контракт DSL (Camel-style Python)::

    .jsonpath(expr="$.users[?(@.age > 18)].name", to="body.adults")

YAML-форма::

    - jsonpath:
        expr: "$.users[?(@.age > 18)].name"
        to: body.adults

Feature flag: ``feature_flags.proc_jsonpath`` (default-OFF).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.registry import processor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange


__all__ = ("JsonPathProcessor",)


@processor(
    "jsonpath",
    namespace="core",
    spec_schema={
        "type": "object",
        "properties": {
            "expr": {"type": "string"},
            "to": {"type": "string"},
            "mode": {"type": "string", "enum": ["all", "first", "scalar"]},
            "default": {},
        },
        "required": ["expr"],
    },
    meta={"tier": 1, "category": "query"},
    tags=("jsonpath", "query", "transform"),
)
class JsonPathProcessor(BaseProcessor):
    """Извлекает значения из тела через JSONPath-выражение.

    Args:
        expr: JSONPath-выражение (``$.users[*].name``, ``$.order.total``).
        to: Куда положить результат: ``body.<field>`` / ``properties.<name>``.
        mode: ``all`` (default — list всех значений), ``first`` (первое
            значение или None), ``scalar`` (единственное значение, иначе
            None / default).
        default: Значение по умолчанию для ``first``/``scalar``, если матча нет.
    """

    def __init__(
        self,
        expr: str,
        *,
        to: str = "body.jsonpath_result",
        mode: str = "all",
        default: Any = None,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"jsonpath:{expr[:32]}")
        if not expr:
            raise ValueError("jsonpath: expr must be non-empty")
        if mode not in {"all", "first", "scalar"}:
            raise ValueError(
                f"jsonpath: mode must be 'all'|'first'|'scalar', got {mode!r}"
            )
        self._expr_source = expr
        self._target = to
        self._mode = mode
        self._default = default

    def _apply_target(self, exchange: Exchange[Any], value: Any) -> None:
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

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Выполняет JSONPath-запрос над body и пишет результат в target."""
        try:
            from src.backend.core.config.features import feature_flags

            if not feature_flags.proc_jsonpath:
                exchange.set_property("jsonpath_status", "skipped")
                return
        except Exception as _:
            pass

        try:
            from jsonpath_ng.ext import parse as _parse
        except ImportError:
            try:
                from jsonpath_ng import parse as _parse
            except ImportError as exc:
                exchange.fail(f"jsonpath: jsonpath-ng not available: {exc}")
                return

        body = exchange.in_message.body
        try:
            expr = _parse(self._expr_source)
            matches = [m.value for m in expr.find(body)]
        except Exception as exc:
            exchange.fail(f"jsonpath evaluation error: {exc}")
            return

        match self._mode:
            case "all":
                result: Any = matches
            case "first":
                result = matches[0] if matches else self._default
            case "scalar":
                result = matches[0] if len(matches) == 1 else self._default
            case _:
                result = matches

        self._apply_target(exchange, result)

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {"expr": self._expr_source}
        if self._target != "body.jsonpath_result":
            spec["to"] = self._target
        if self._mode != "all":
            spec["mode"] = self._mode
        if self._default is not None:
            spec["default"] = self._default
        return {"jsonpath": spec}
