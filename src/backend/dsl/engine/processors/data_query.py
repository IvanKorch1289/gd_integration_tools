"""DSL Data-query процессоры — JSONPath / Jq-style выражения над body.

Pure-Python deps:
- jsonpath-ng (lazy import) — RFC-9535 совместимый JSONPath.

Все процессоры graceful fallback при отсутствии библиотеки —
сообщение об ошибке с подсказкой по установке.
"""

from __future__ import annotations

from typing import Any, ClassVar

from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

__all__ = ("JsonPathProcessor",)


class JsonPathProcessor(BaseProcessor):
    """Извлечение/обновление значений из body по JSONPath-выражению.

    Body должен быть dict/list (либо JSON-строка — будет автоматически
    декодирована). На вход — JSONPath expression (стандарт jsonpath-ng).

    Режимы:
    - ``mode="extract"`` (default): возвращает list совпадений;
      при ``single=True`` — первое значение или ``None``.
    - ``mode="update"``: заменяет значения по path на ``value``,
      возвращает обновлённый объект.
    - ``mode="exists"``: устанавливает property ``jsonpath_exists`` (bool)
      и при ``stop_on_missing=True`` останавливает pipeline если совпадений 0.

    Результат записывается в ``out_message.body`` (или, при ``to_property``,
    в ``set_property(<name>)`` без замены body).

    Usage::
        .jsonpath("$.user.email", to_property="user_email", single=True)
        .jsonpath("$.items[*].price", mode="extract")
        .jsonpath("$.status", mode="update", value="approved")
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.PURE
    compensatable: ClassVar[bool] = True

    def __init__(
        self,
        expression: str,
        *,
        mode: str = "extract",
        value: Any = None,
        single: bool = False,
        to_property: str | None = None,
        stop_on_missing: bool = False,
        name: str | None = None,
    ) -> None:
        if mode not in {"extract", "update", "exists"}:
            raise ValueError(f"Unsupported jsonpath mode: {mode}")
        super().__init__(name=name or f"jsonpath:{mode}")
        self._expr_text = expression
        self._mode = mode
        self._value = value
        self._single = single
        self._to_property = to_property
        self._stop_on_missing = stop_on_missing

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        try:
            from jsonpath_ng.ext import (
                parse as jp_parse,  
            )
        except ImportError:
            exchange.fail("jsonpath-ng not installed: pip install 'jsonpath-ng>=1.6'")
            return

        body = exchange.in_message.body
        if isinstance(body, (bytes, bytearray)):
            try:
                body = body.decode("utf-8")
            except UnicodeDecodeError:
                exchange.fail("jsonpath: body bytes must be utf-8")
                return
        if isinstance(body, str):
            try:
                import orjson

                body = orjson.loads(body)
            except Exception as exc:
                exchange.fail(f"jsonpath: body is not valid JSON ({exc})")
                return

        try:
            expr = jp_parse(self._expr_text)
        except Exception as exc:
            exchange.fail(f"jsonpath: bad expression {self._expr_text!r}: {exc}")
            return

        matches = expr.find(body)
        match self._mode:
            case "extract":
                values = [m.value for m in matches]
                if self._stop_on_missing and not values:
                    exchange.set_property("jsonpath_exists", False)
                    exchange.stop()
                    return
                result: Any = (
                    (values[0] if values else None) if self._single else values
                )
                self._emit(exchange, result)
            case "update":
                updated = expr.update(body, self._value)
                self._emit(exchange, updated)
            case "exists":
                exists = bool(matches)
                exchange.set_property("jsonpath_exists", exists)
                if not exists and self._stop_on_missing:
                    exchange.stop()

    def _emit(self, exchange: Exchange[Any], result: Any) -> None:
        if self._to_property:
            exchange.set_property(self._to_property, result)
        else:
            exchange.set_out(body=result, headers=dict(exchange.in_message.headers))

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {"expression": self._expr_text}
        if self._mode != "extract":
            spec["mode"] = self._mode
        if self._value is not None:
            spec["value"] = self._value
        if self._single:
            spec["single"] = True
        if self._to_property is not None:
            spec["to_property"] = self._to_property
        if self._stop_on_missing:
            spec["stop_on_missing"] = True
        return {"jsonpath": spec}
