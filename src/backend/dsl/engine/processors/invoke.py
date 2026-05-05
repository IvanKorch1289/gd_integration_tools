"""DSL processor ``invoke`` (W22.4).

Связывает DSL pipeline с :class:`Invoker` — главным Gateway вызовов
(W22). Отличается от :class:`DispatchActionProcessor` тем, что
поддерживает все шесть режимов :class:`InvocationMode` и единый
``invocation_id`` для трассировки и polling-результата.

Поведение по статусам :class:`InvocationStatus`:

* ``OK`` — ``response.result`` пишется в ``out_message.body`` и в
  ``exchange.property[result_property]``.
* ``ACCEPTED`` — body не меняется; ``invocation_id`` пишется в
  ``property[invocation_id_property]`` для последующего polling-а.
* ``ERROR`` — текст ошибки пишется в ``property[result_property]``,
  Exchange останавливается (``exchange.stop()``); это даёт чёткий
  signal для последующих процессоров (Choice/TryCatch).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from src.backend.core.interfaces.invoker import (
    InvocationMode,
    InvocationRequest,
    InvocationStatus,
    Invoker,
)
from src.backend.dsl.engine.processors.base import BaseProcessor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

__all__ = ("InvokeProcessor",)


class InvokeProcessor(BaseProcessor):
    """DSL-процессор универсального вызова через :class:`Invoker`."""

    def __init__(
        self,
        action: str,
        *,
        mode: str | InvocationMode = InvocationMode.SYNC,
        payload_factory: Callable[["Exchange[Any]"], dict[str, Any]] | None = None,
        reply_channel: str | None = None,
        result_property: str = "invoke_result",
        invocation_id_property: str = "invocation_id",
        timeout: float | None = None,
        correlation_id: str | None = None,
        invoker: Invoker | None = None,
    ) -> None:
        super().__init__(name=f"invoke:{action}")
        self.action = action
        self.mode = self._coerce_mode(mode, action=action)
        self.payload_factory = payload_factory
        self.reply_channel = reply_channel
        self.result_property = result_property
        self.invocation_id_property = invocation_id_property
        self.timeout = self._coerce_timeout(timeout, action=action)
        self.correlation_id = correlation_id
        # Invoker инжектится через DI; при отсутствии берём singleton — но
        # импорт singleton'а откладываем до runtime, чтобы избежать
        # циклических импортов при регистрации pipeline в reflection.
        self._invoker_override = invoker

    @staticmethod
    def _coerce_mode(value: str | InvocationMode, *, action: str) -> InvocationMode:
        """Pretty-валидация mode с перечнем допустимых значений (B1).

        Голый ``InvocationMode(value)`` бросает Python-ValueError без
        контекста. На уровне DSL/YAML это приводит к непрозрачному
        сообщению — оборачиваем в типизированный ValueError с указанием
        action и допустимого набора режимов.
        """
        if isinstance(value, InvocationMode):
            return value
        try:
            return InvocationMode(value)
        except ValueError as exc:
            allowed = ", ".join(m.value for m in InvocationMode)
            raise ValueError(
                f"invoke[{action}]: невалидный mode={value!r}. Допустимые: {allowed}."
            ) from exc

    @staticmethod
    def _coerce_timeout(
        value: float | int | str | None, *, action: str
    ) -> float | None:
        """Валидация timeout: положительное число или ``None``."""
        if value is None:
            return None
        try:
            timeout = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"invoke[{action}]: timeout={value!r} не является числом."
            ) from exc
        if timeout <= 0:
            raise ValueError(
                f"invoke[{action}]: timeout должен быть > 0, получено {timeout}."
            )
        return timeout

    def _resolve_invoker(self) -> Invoker:
        if self._invoker_override is not None:
            return self._invoker_override
        from src.backend.services.execution.invoker import get_invoker

        return get_invoker()

    async def process(
        self, exchange: "Exchange[Any]", context: "ExecutionContext"
    ) -> None:
        """Вызывает action через ``Invoker`` и записывает результат/ошибку в ``exchange``."""
        if self.payload_factory is not None:
            payload = self.payload_factory(exchange)
        else:
            body = exchange.in_message.body
            payload = body if isinstance(body, dict) else {}

        request = InvocationRequest(
            action=self.action,
            payload=payload,
            mode=self.mode,
            reply_channel=self.reply_channel,
            timeout=self.timeout,
            correlation_id=self.correlation_id,
        )
        response = await self._resolve_invoker().invoke(request)

        exchange.set_property(self.invocation_id_property, response.invocation_id)

        match response.status:
            case InvocationStatus.OK:
                exchange.set_property(self.result_property, response.result)
                exchange.set_out(
                    body=response.result, headers=dict(exchange.in_message.headers)
                )
            case InvocationStatus.ACCEPTED:
                exchange.set_property(
                    self.result_property,
                    {"accepted": True, "invocation_id": response.invocation_id},
                )
            case InvocationStatus.ERROR:
                exchange.set_property(self.result_property, {"error": response.error})
                exchange.stop()

    def to_spec(self) -> dict[str, Any] | None:
        """Возвращает round-trip DSL-спецификацию ``{"invoke": {...}}``."""
        spec: dict[str, Any] = {"action": self.action, "mode": self.mode.value}
        if self.reply_channel is not None:
            spec["reply_channel"] = self.reply_channel
        if self.result_property != "invoke_result":
            spec["result_property"] = self.result_property
        if self.invocation_id_property != "invocation_id":
            spec["invocation_id_property"] = self.invocation_id_property
        if self.timeout is not None:
            spec["timeout"] = self.timeout
        if self.correlation_id is not None:
            spec["correlation_id"] = self.correlation_id
        return {"invoke": spec}
