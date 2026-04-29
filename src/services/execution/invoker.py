"""Реализация Invoker (W22.1).

Минимальный, но работоспособный invoker для режима ``SYNC``. Остальные
режимы прорастают в W22.2 (адаптеры протоколов), W22.3 (ReplyChannel),
W22.4 (DSL processor ``invoke``), W22.5 (Streamlit Console).

Контракт W22.4 — DSL processor ``invoke`` — может быть реализован поверх
этого класса без модификации ядра.
"""

from __future__ import annotations

import logging
from typing import Any

from src.core.interfaces.action_dispatcher import ActionDispatcher
from src.core.interfaces.invoker import (
    InvocationMode,
    InvocationRequest,
    InvocationResponse,
    InvocationStatus,
)
from src.core.interfaces.invoker import Invoker as InvokerProtocol
from src.schemas.invocation import ActionCommandSchema
from src.services.execution.action_dispatcher import get_action_dispatcher

__all__ = ("Invoker", "InvocationMode", "get_invoker")

logger = logging.getLogger("services.execution.invoker")


class Invoker(InvokerProtocol):
    """Каркасная реализация Invoker (sync-mode + заглушки)."""

    def __init__(self, dispatcher: ActionDispatcher | None = None) -> None:
        self._dispatcher = dispatcher or get_action_dispatcher()

    async def invoke(self, request: InvocationRequest) -> InvocationResponse:
        match request.mode:
            case InvocationMode.SYNC:
                return await self._invoke_sync(request)
            case (
                InvocationMode.ASYNC_API
                | InvocationMode.ASYNC_QUEUE
                | InvocationMode.DEFERRED
                | InvocationMode.BACKGROUND
                | InvocationMode.STREAMING
            ):
                return InvocationResponse(
                    invocation_id=request.invocation_id,
                    status=InvocationStatus.ERROR,
                    error=f"Mode '{request.mode.value}' is not yet implemented (W22.2+)",
                    mode=request.mode,
                )

    async def _invoke_sync(self, request: InvocationRequest) -> InvocationResponse:
        try:
            command = ActionCommandSchema(action=request.action, payload=request.payload)
            result: Any = await self._dispatcher.dispatch(command)
            return InvocationResponse(
                invocation_id=request.invocation_id,
                status=InvocationStatus.OK,
                result=result,
                mode=request.mode,
            )
        except KeyError as exc:
            return InvocationResponse(
                invocation_id=request.invocation_id,
                status=InvocationStatus.ERROR,
                error=f"Action not registered: {exc}",
                mode=request.mode,
            )
        except Exception as exc:
            logger.exception(
                "Invoker.invoke failed: action=%s id=%s",
                request.action,
                request.invocation_id,
            )
            return InvocationResponse(
                invocation_id=request.invocation_id,
                status=InvocationStatus.ERROR,
                error=str(exc)[:500],
                mode=request.mode,
            )


_invoker_singleton: Invoker | None = None


def get_invoker() -> Invoker:
    """Singleton-доступ к Invoker'у (для DI и DSL processors)."""
    global _invoker_singleton
    if _invoker_singleton is None:
        _invoker_singleton = Invoker()
    return _invoker_singleton
