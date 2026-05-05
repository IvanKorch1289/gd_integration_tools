"""R2.7 — `InvokeAsyncProcessor`: fire-and-forget action invocation.

DSL processor: запускает action через ``ActionGatewayDispatcher``
без блокировки основного pipeline. Дополняет существующие
``LoopProcessor`` / ``ThrottlerProcessor`` / ``WireTapProcessor``
для случаев, когда нужно «дёрнуть и забыть» (notifications, audit
side-effects, asynchronous post-processing).

Семантика:

* Возврат — мгновенный (после ``asyncio.create_task``); основной
  pipeline продолжается без ожидания.
* Результат action'а **не пишется** в `exchange` — для этого есть
  `InvokeProcessor` (sync). Ошибки логируются, не пробрасываются.
* `correlation_id` копируется из `exchange.meta.correlation_id` в
  ``DispatchContext`` (если не задан явно).
* `idempotency_key` опционально; рекомендуется для at-least-once
  семантик.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from src.core.interfaces.action_dispatcher import (
    ActionGatewayDispatcher,
    DispatchContext,
)
from src.dsl.engine.context import ExecutionContext
from src.dsl.engine.exchange import Exchange
from src.dsl.engine.processors.base import BaseProcessor

__all__ = ("InvokeAsyncProcessor",)


_logger = logging.getLogger("dsl.invoke_async")


class InvokeAsyncProcessor(BaseProcessor):
    """Fire-and-forget вызов action через `ActionGatewayDispatcher`."""

    def __init__(
        self,
        *,
        action: str,
        dispatcher: ActionGatewayDispatcher,
        payload_path: str = "body",
        idempotency_key_path: str | None = None,
        source: str = "dsl_invoke_async",
        name: str | None = None,
    ) -> None:
        """Параметры:

        :param action: имя action ("orders.notify_status").
        :param dispatcher: ActionGatewayDispatcher (через DI).
        :param payload_path: где взять payload — ``"body"`` (по
            умолчанию) или ``"properties.<key>"``, или
            ``"headers.<key>"``.
        :param idempotency_key_path: опц. путь к ключу идемпотентности
            (например, ``"headers.X-Idempotency-Key"``).
        :param source: транспорт-источник для DispatchContext.
        :param name: имя processor'а в трассировке.
        """
        super().__init__(name=name or f"invoke_async({action})")
        self._action = action
        self._dispatcher = dispatcher
        self._payload_path = payload_path
        self._idempotency_key_path = idempotency_key_path
        self._source = source

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Создать task с dispatcher.dispatch и сразу вернуться."""
        payload = self._extract_payload(exchange)
        ctx = DispatchContext(
            correlation_id=exchange.meta.correlation_id,
            tenant_id=getattr(exchange.meta, "tenant_id", None),
            idempotency_key=self._extract_idempotency_key(exchange),
            source=self._source,
        )

        task = asyncio.create_task(
            self._dispatch_and_log(payload, ctx), name=f"invoke_async:{self._action}"
        )
        # Уберечь loop от warning'а про unawaited exceptions.
        task.add_done_callback(_safe_swallow_exception)
        # Сохраняем task-ref в properties для дебага (опционально).
        exchange.properties.setdefault("invoke_async_tasks", []).append(
            f"invoke_async:{self._action}:{id(task)}"
        )

    async def _dispatch_and_log(
        self, payload: dict[str, Any], ctx: DispatchContext
    ) -> None:
        """Корутина внутри background task: dispatch + лог при ошибке."""
        try:
            result = await self._dispatcher.dispatch(self._action, payload, ctx)
            if not result.success:
                _logger.warning(
                    "invoke_async failed: action=%s, error=%s",
                    self._action,
                    result.error.message if result.error else "?",
                )
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "invoke_async exception: action=%s, exc=%s", self._action, exc
            )

    def _extract_payload(self, exchange: Exchange[Any]) -> dict[str, Any]:
        """Извлечь payload по `payload_path`."""
        path = self._payload_path
        if path == "body":
            body = exchange.in_message.body
            return body if isinstance(body, dict) else {"value": body}
        if path.startswith("properties."):
            key = path.removeprefix("properties.")
            value = exchange.properties.get(key)
            return value if isinstance(value, dict) else {"value": value}
        if path.startswith("headers."):
            key = path.removeprefix("headers.")
            value = exchange.in_message.headers.get(key)
            return value if isinstance(value, dict) else {"value": value}
        raise ValueError(f"InvokeAsyncProcessor: unsupported payload_path={path!r}")

    def _extract_idempotency_key(self, exchange: Exchange[Any]) -> str | None:
        """Достать idempotency key по `idempotency_key_path`."""
        path = self._idempotency_key_path
        if path is None:
            return None
        if path.startswith("headers."):
            key = path.removeprefix("headers.")
            value = exchange.in_message.headers.get(key)
            return str(value) if value is not None else None
        if path.startswith("properties."):
            key = path.removeprefix("properties.")
            value = exchange.properties.get(key)
            return str(value) if value is not None else None
        return None


def _safe_swallow_exception(task: asyncio.Task[None]) -> None:
    """Done-callback: гасит unhandled exception у background task."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        _logger.debug("invoke_async background task exception: %s", exc)
