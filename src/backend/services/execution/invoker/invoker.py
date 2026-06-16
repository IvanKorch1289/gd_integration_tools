"""S68 W3 - invoker.py part of invoker decomp.

Classes: Invoker.
"""

from __future__ import annotations

import asyncio
from typing import Any

from src.backend.core.di.contexts import DispatchContext
from src.backend.core.di.dependencies import get_reply_registry_singleton
from src.backend.core.interfaces.action_dispatcher import ActionDispatcher
from src.backend.core.interfaces.invocation_reply import ReplyChannelRegistryProtocol
from src.backend.core.interfaces.invoker import (
    InvocationMode,
    InvocationRequest,
    InvocationResponse,
)
from src.backend.core.types.invocation_command import ActionCommandSchema
from src.backend.services.execution.action_dispatcher import get_action_dispatcher
from src.backend.services.execution.invoker.deferred_mixin import (
    DeferredMixin,  # S54 W3: MRO
)
from src.backend.services.execution.invoker.invoke_modes_mixin import (
    InvokeModesMixin,  # S54 W3: MRO
)
from src.backend.services.execution.invoker.run_mixin import RunMixin  # S54 W3: MRO
from src.backend.services.execution.invoker.temporal_mixin import (
    TemporalMixin,  # S54 W3: MRO
)


class Invoker(InvokeModesMixin, DeferredMixin, TemporalMixin, RunMixin):
    """Action invoker (4 mixins = 15 methods + 5 core)."""

    __slots__ = ("_dispatcher", "_reply_registry_override", "_tasks")

    def __init__(
        self,
        dispatcher: ActionDispatcher | None = None,
        *,
        reply_registry: ReplyChannelRegistryProtocol | None = None,
    ) -> None:
        self._dispatcher = dispatcher or get_action_dispatcher()
        # ReplyChannelRegistry инжектится опционально; lazy-резолв
        # из app.state через core/di сохраняет совместимость с
        # вызывающими, которые передавали только dispatcher (тесты).
        self._reply_registry_override = reply_registry
        # Активные fire-and-forget tasks хранятся, чтобы их не собрал GC
        # до завершения; auto-cleanup на done.
        self._tasks: set[asyncio.Task[None]] = set()

    def _resolve_reply_registry(self) -> ReplyChannelRegistryProtocol | None:
        if self._reply_registry_override is not None:
            return self._reply_registry_override
        try:
            return get_reply_registry_singleton()
        except RuntimeError:
            return None

    async def _dispatch(
        self, command: ActionCommandSchema, context: DispatchContext
    ) -> Any:
        """Прокси к dispatcher.dispatch с проброшенным DispatchContext.

        Контекст пробрасывается keyword-аргументом, чтобы legacy-моки в
        тестах (без kwarg ``context``) могли быть совместимы — для них
        делается fallback на однопозиционный вызов.
        """
        try:
            return await self._dispatcher.dispatch(command, context=context)
        except TypeError:
            # Legacy ActionDispatcher Protocol (без context-параметра) —
            # вызываем без context, теряем middleware-цепочку только в
            # этом узком сценарии (тесты/устаревшие реализации).
            return await self._dispatcher.dispatch(command)

    @staticmethod
    def _build_context(request: InvocationRequest) -> DispatchContext:
        """Строит :class:`DispatchContext` из :class:`InvocationRequest` (W22 F.2 A1).

        Поля контекста:
        * ``correlation_id`` берётся из request.correlation_id (если задан).
        * ``source`` = ``"invoker"`` — обозначает, что вызов инициирован
          через Invoker Gateway (а не напрямую транспортом).
        * ``attributes`` дополнительно несут ``invocation_id`` и
          ``invocation_mode`` для middleware (audit/idempotency).
        """
        attrs: dict[str, Any] = {
            "invocation_id": request.invocation_id,
            "invocation_mode": request.mode.value,
        }
        if request.metadata:
            attrs["request_metadata"] = dict(request.metadata)
        return DispatchContext(
            correlation_id=request.correlation_id, source="invoker", attributes=attrs
        )

    async def invoke(self, request: InvocationRequest) -> InvocationResponse:
        match request.mode:
            case InvocationMode.SYNC:
                return await self._invoke_sync(request)
            case InvocationMode.ASYNC_API:
                return self._invoke_async_api(request)
            case InvocationMode.BACKGROUND:
                return self._invoke_background(request)
            case InvocationMode.STREAMING:
                return self._invoke_streaming(request)
            case InvocationMode.DEFERRED:
                return self._invoke_deferred(request)
            case InvocationMode.ASYNC_QUEUE:
                return await self._invoke_async_queue(request)
