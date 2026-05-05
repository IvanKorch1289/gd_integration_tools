"""W23.7 — :class:`GrpcSource` (gRPC server-streaming клиент).

Подключается к удалённому gRPC-сервису, вызывает указанный server-streaming
метод и эмитит ``SourceEvent`` на каждое сообщение из стрима. Оборачивает
``grpc.aio.Channel`` (уже в зависимостях через ``grpcio``).

Конкретные ``stub_factory`` и ``request`` приходят из YAML-spec через
динамический импорт — это позволяет добавлять новые .proto-сервисы без
изменения класса-источника.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
from datetime import UTC, datetime
from typing import Any

from src.backend.core.interfaces.source import EventCallback, SourceEvent, SourceKind
from src.backend.infrastructure.sources._lifecycle import graceful_cancel

__all__ = ("GrpcSource",)

logger = logging.getLogger("infrastructure.sources.grpc")


class GrpcSource:
    """gRPC server-streaming Source.

    Args:
        source_id: Уникальный id.
        target: ``host:port`` gRPC-сервиса.
        stub_module: Полный путь к модулю stubs (``my.pb2_grpc``).
        stub_class: Имя stub-класса (например ``MarketDataStub``).
        method: Имя server-streaming метода.
        request_module: Путь к модулю с request-message классом.
        request_class: Имя request-класса.
        request_kwargs: Аргументы конструктора request (``param=value``).
        secure: Использовать ли TLS (default ``False``, для prod установить ``True``).
        reconnect_delay_seconds: Задержка перед реконнектом.
    """

    kind: SourceKind = SourceKind.GRPC

    def __init__(
        self,
        source_id: str,
        *,
        target: str,
        stub_module: str,
        stub_class: str,
        method: str,
        request_module: str,
        request_class: str,
        request_kwargs: dict[str, Any] | None = None,
        secure: bool = False,
        reconnect_delay_seconds: float = 2.0,
    ) -> None:
        self.source_id = source_id
        self._target = target
        self._stub_module = stub_module
        self._stub_class = stub_class
        self._method = method
        self._req_module = request_module
        self._req_class = request_class
        self._req_kwargs = request_kwargs or {}
        self._secure = secure
        self._reconnect = reconnect_delay_seconds
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    async def start(self, on_event: EventCallback) -> None:
        if self._task is not None and not self._task.done():
            raise RuntimeError(f"GrpcSource(id={self.source_id!r}) уже запущен")
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run(on_event))
        logger.info(
            "GrpcSource started: id=%s target=%s method=%s",
            self.source_id,
            self._target,
            self._method,
        )

    async def stop(self) -> None:
        self._stop_event.set()
        await graceful_cancel(self._task, source_id=self.source_id)
        self._task = None

    async def health(self) -> bool:
        return self._task is not None and not self._task.done()

    async def _run(self, on_event: EventCallback) -> None:
        import grpc

        stub_mod = importlib.import_module(self._stub_module)
        stub_cls = getattr(stub_mod, self._stub_class)
        req_mod = importlib.import_module(self._req_module)
        req_cls = getattr(req_mod, self._req_class)

        while not self._stop_event.is_set():
            try:
                channel = (
                    grpc.aio.secure_channel(
                        self._target, grpc.ssl_channel_credentials()
                    )
                    if self._secure
                    else grpc.aio.insecure_channel(self._target)
                )
                async with channel:
                    stub = stub_cls(channel)
                    method = getattr(stub, self._method)
                    request = req_cls(**self._req_kwargs)
                    async for resp in method(request):
                        if self._stop_event.is_set():
                            break
                        event = SourceEvent(
                            source_id=self.source_id,
                            kind=self.kind,
                            payload=resp,
                            event_time=datetime.now(UTC),
                            metadata={"target": self._target, "method": self._method},
                        )
                        try:
                            await on_event(event)
                        except Exception as exc:
                            logger.error("GrpcSource on_event failed: %s", exc)
            except Exception as exc:
                logger.warning(
                    "GrpcSource %s: stream error: %s; reconnect in %.1fs",
                    self._target,
                    exc,
                    self._reconnect,
                )
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=self._reconnect
                    )
                except TimeoutError:
                    continue
