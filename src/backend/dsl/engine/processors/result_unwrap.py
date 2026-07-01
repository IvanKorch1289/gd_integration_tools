"""K3 S5 W12 — DSL-процессор ``result_unwrap`` (rust-style Result monad).

Wave ``[wave:s5/k3-w12-result-monad]``.

Использует библиотеку ``result>=0.17`` (extra ``result-monad``). Lazy-import:
если библиотека не установлена, процессор fail-завершается с понятной ошибкой.

Контракт DSL::

    .result_unwrap(source="body.maybe_result", to="body.value", on_err="dlq")

Поведение:
* если payload — ``Ok(value)`` → положить ``value`` в ``to`` и продолжить;
* если payload — ``Err(error)`` → вызвать обработку по ``on_err``:
    - ``"dlq"`` — пометить exchange ``_dlq=True``, ``_err=<repr>``;
    - ``"fail"`` — exchange.fail();
    - ``"continue"`` — положить ``error`` в ``to_err`` и продолжить.

Feature flag: ``feature_flags.result_unwrap_processor`` (default-OFF).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.registry import processor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange


__all__ = ("ResultUnwrapProcessor",)


_ALLOWED_ON_ERR = frozenset({"dlq", "fail", "continue"})


@processor(
    "result_unwrap",
    namespace="core",
    spec_schema={
        "type": "object",
        "properties": {
            "source": {"type": "string"},
            "to": {"type": "string"},
            "to_err": {"type": "string"},
            "on_err": {"type": "string", "enum": sorted(_ALLOWED_ON_ERR)},
        },
    },
    meta={"tier": 1, "category": "control_flow"},
    tags=("result", "monad", "rust"),
)
class ResultUnwrapProcessor(BaseProcessor):
    """Распаковать ``result.Ok``/``result.Err`` из payload.

    Args:
        source: Откуда брать Result-значение (``body``, ``body.<f>``, ``properties.<n>``).
        to: Куда положить unwrapped value (на Ok).
        to_err: Куда положить error (на Err при ``on_err='continue'``).
        on_err: Стратегия для Err — ``dlq`` / ``fail`` / ``continue``.
    """

    def __init__(
        self,
        *,
        source: str = "body",
        to: str = "body.unwrapped",
        to_err: str = "body.err",
        on_err: str = "dlq",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "result_unwrap")
        if on_err not in _ALLOWED_ON_ERR:
            raise ValueError(
                f"result_unwrap: on_err must be one of {sorted(_ALLOWED_ON_ERR)}, "
                f"got {on_err!r}"
            )
        self._source = source
        self._target = to
        self._target_err = to_err
        self._on_err = on_err

    def _resolve_source(self, exchange: Exchange[Any]) -> Any:
        body = exchange.in_message.body
        if self._source == "body":
            return body
        if self._source.startswith("body."):
            field = self._source[len("body.") :]
            return body.get(field) if isinstance(body, dict) else None
        if self._source.startswith("properties."):
            field = self._source[len("properties.") :]
            return exchange.properties.get(field)
        return None

    def _apply_target(self, exchange: Exchange[Any], target: str, value: Any) -> None:
        if target.startswith("body."):
            field = target[len("body.") :]
            body = exchange.in_message.body
            if not isinstance(body, dict):
                body = {}
                exchange.in_message.body = body
            body[field] = value
            return
        if target.startswith("properties."):
            field = target[len("properties.") :]
            exchange.set_property(field, value)
            return
        exchange.set_property(target, value)

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Разворачивает Result(Ok/Err) и пишет значение в target, при Err — fail."""
        try:
            from src.backend.core.config.features import feature_flags

            if not feature_flags.result_unwrap_processor:
                exchange.set_property("result_unwrap_status", "skipped")
                return
        except Exception as _:
            pass

        # Lazy-import result library (extra)
        try:
            from result import Err, Ok  # type: ignore[import-not-found]
        except ImportError as exc:
            exchange.fail(f"result_unwrap: result>=0.17 not available: {exc}")
            return

        value = self._resolve_source(exchange)

        if isinstance(value, Ok):
            self._apply_target(exchange, self._target, value.ok_value)
            return

        if isinstance(value, Err):
            err_value = value.err_value
            match self._on_err:
                case "fail":
                    exchange.fail(f"result_unwrap: {err_value!r}")
                case "dlq":
                    exchange.set_property("_dlq", True)
                    exchange.set_property("_err", repr(err_value))
                case "continue":
                    self._apply_target(exchange, self._target_err, err_value)
            return

        # Не Result — записываем как есть (no-op)
        self._apply_target(exchange, self._target, value)

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {}
        if self._source != "body":
            spec["source"] = self._source
        if self._target != "body.unwrapped":
            spec["to"] = self._target
        if self._target_err != "body.err":
            spec["to_err"] = self._target_err
        if self._on_err != "dlq":
            spec["on_err"] = self._on_err
        return {"result_unwrap": spec}
