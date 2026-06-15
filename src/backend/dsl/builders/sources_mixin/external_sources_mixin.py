"""S132 W4 — external sources mixin: gRPC server-streaming source.

1 method (TD-011 partial): ``from_grpc_stream``.

.. note::
    S132 W4 scope reduced from 3 to 1 after factcheck (S132 W1 + W4 self-review):
    - ``from_nats`` ALREADY EXISTS в ``src/backend/dsl/builders/transport/sources.py``
      (S106 W4, feature-flag ``nats_core_dsl`` default-OFF) — не дублируем (R10).
    - ``from_mongo`` ALREADY EXISTS в ``src/backend/dsl/builders/transport/sources.py``
      — не дублируем (R10).
    - ``from_grpc_stream`` is genuinely NEW (no prior implementation anywhere) — added.

Backward-compat: 1 new classmethod on ``SourcesMixin`` (exposed via ``RouteBuilder``).
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.dsl.builders.base import RouteBuilder


class ExternalSourcesMixin:
    """External system sources (gRPC server-streaming) для RouteBuilder.

    S132 W4 (TD-011, partial). 1 method total.
    """

    __slots__ = ()

    @classmethod
    def from_grpc_stream(
        cls,
        route_id: str,
        target: str,
        stub_module: str,
        stub_class: str,
        method: str,
        request_module: str,
        request_class: str,
        request_kwargs: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> RouteBuilder:
        """gRPC server-streaming source. See GrpcSource in infrastructure.sources.grpc.

        Лениво импортирует :class:`GrpcSource` из
        ``infrastructure.sources.grpc`` (``grpcio`` + ``grpc-interceptor``).

        Args:
            route_id: Уникальный ID маршрута.
            target: ``host:port`` gRPC-сервиса.
            stub_module: Полный путь к модулю stubs (``my_service_pb2_grpc``).
            stub_class: Имя stub-класса (``MarketDataStub``).
            method: Имя server-streaming метода (``SubscribeTicks``).
            request_module: Путь к модулю с request-message классом.
            request_class: Имя request-класса.
            request_kwargs: Аргументы конструктора request (default ``None``).
            **kwargs: Доп. параметры (forwarded to GrpcSource:
                ``secure``, ``reconnect_delay_seconds``, etc.).

        Returns:
            RouteBuilder с ``source`` = ``grpc_stream:<service>/<method>``.

        Example::

            route = (
                RouteBuilder.from_grpc_stream(
                    "market.feed",
                    target="marketdata:50051",
                    stub_module="my.pkg.marketdata_pb2_grpc",
                    stub_class="MarketDataStub",
                    method="SubscribeTicks",
                    request_module="my.pkg.marketdata_pb2",
                    request_class="SubscribeRequest",
                    request_kwargs={"symbol": "AAPL"},
                )
                .dispatch_action("market.process_tick")
                .build()
            )
        """
        mod = importlib.import_module("src.backend.infrastructure.sources.grpc")
        GrpcSource = mod.GrpcSource
        source_instance = GrpcSource(
            source_id=route_id,
            target=target,
            stub_module=stub_module,
            stub_class=stub_class,
            method=method,
            request_module=request_module,
            request_class=request_class,
            request_kwargs=request_kwargs,
            **kwargs,
        )
        builder: RouteBuilder = cls(
            route_id=route_id, source=f"grpc_stream:{stub_class}/{method}"
        )
        object.__setattr__(builder, "_source_instance", source_instance)
        return builder
