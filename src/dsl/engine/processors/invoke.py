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

from src.core.interfaces.invoker import (
    InvocationMode,
    InvocationRequest,
    InvocationStatus,
    Invoker,
)
from src.dsl.engine.processors.base import BaseProcessor

if TYPE_CHECKING:
    from src.dsl.engine.context import ExecutionContext
    from src.dsl.engine.exchange import Exchange

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
        invoker: Invoker | None = None,
    ) -> None:
        super().__init__(name=f"invoke:{action}")
        self.action = action
        self.mode: InvocationMode = (
            mode if isinstance(mode, InvocationMode) else InvocationMode(mode)
        )
        self.payload_factory = payload_factory
        self.reply_channel = reply_channel
        self.result_property = result_property
        self.invocation_id_property = invocation_id_property
        # Invoker инжектится через DI; при отсутствии берём singleton — но
        # импорт singleton'а откладываем до runtime, чтобы избежать
        # циклических импортов при регистрации pipeline в reflection.
        self._invoker_override = invoker

    def _resolve_invoker(self) -> Invoker:
        if self._invoker_override is not None:
            return self._invoker_override
        from src.services.execution.invoker import get_invoker

        return get_invoker()

    async def process(
        self, exchange: "Exchange[Any]", context: "ExecutionContext"
    ) -> None:
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
        spec: dict[str, Any] = {"action": self.action, "mode": self.mode.value}
        if self.reply_channel is not None:
            spec["reply_channel"] = self.reply_channel
        if self.result_property != "invoke_result":
            spec["result_property"] = self.result_property
        if self.invocation_id_property != "invocation_id":
            spec["invocation_id_property"] = self.invocation_id_property
        return {"invoke": spec}
