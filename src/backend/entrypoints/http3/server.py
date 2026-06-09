"""HTTP/3 + WebTransport ASGI server.

Тонкий wrapper над ``aioquic.asyncio.serve``: создаёт ``QuicConfiguration``
из :class:`Http3ServerConfig`, регистрирует ASGI-bridge как
``QuicConnectionProtocol`` и запускает сервер до отмены.

Зависимость ``aioquic`` подгружается лениво — модуль импортируется без
extra ``http3`` (ImportError возникает только при вызове ``serve_http3``).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from src.backend.core.logging import get_logger
from src.backend.entrypoints.http3.asgi_bridge import (
    HttpStreamHandler,
    build_http_scope,
)
from src.backend.entrypoints.http3.config import Http3ServerConfig

if TYPE_CHECKING:  # pragma: no cover
    from aioquic.asyncio.protocol import QuicConnectionProtocol  # noqa: F401

logger = get_logger(__name__)

ASGIApp = Callable[
    [
        dict[str, Any],
        Callable[[], Awaitable[dict[str, Any]]],
        Callable[[dict[str, Any]], Awaitable[None]],
    ],
    Awaitable[None],
]

__all__ = ("build_quic_configuration", "serve_http3")


def build_quic_configuration(config: Http3ServerConfig) -> Any:
    """Собрать ``aioquic.QuicConfiguration`` для server-mode.

    Вынесено отдельно для возможности unit-тестирования без сетевого
    запуска (см. ``tests/unit/entrypoints/http3``).
    """
    from aioquic.quic.configuration import QuicConfiguration

    quic_config = QuicConfiguration(
        is_client=False,
        alpn_protocols=list(config.alpn_protocols),
        max_datagram_frame_size=config.max_datagram_frame_size,
        idle_timeout=config.idle_timeout,
    )
    quic_config.load_cert_chain(str(config.certfile), str(config.keyfile))
    return quic_config


async def serve_http3(
    app: ASGIApp, config: Http3ServerConfig, *, stop_event: asyncio.Event | None = None
) -> None:
    """Запустить HTTP/3 ASGI-сервер.

    Args:
        app: ASGI 3.0 application (например, FastAPI).
        config: параметры HTTP/3 сервера (TLS, порт, idle timeout).
        stop_event: внешнее событие отмены; если ``None`` — сервер
            работает до ``CancelledError``.
    """
    from aioquic.asyncio import serve

    quic_config = build_quic_configuration(config)

    def _protocol_factory(*proto_args: Any, **proto_kwargs: Any) -> Any:
        from src.backend.entrypoints.http3._protocol import AsgiHttp3Protocol

        return AsgiHttp3Protocol(
            *proto_args, asgi_app=app, server_config=config, **proto_kwargs
        )

    server = await serve(
        host=config.host,
        port=config.port,
        configuration=quic_config,
        create_protocol=_protocol_factory,
    )
    logger.info(
        "HTTP/3 server started",
        extra={"host": config.host, "port": config.port, "alpn": config.alpn_protocols},
    )

    try:
        if stop_event is None:
            await asyncio.Future()  # бесконечное ожидание
        else:
            await stop_event.wait()
    finally:
        server.close()
        logger.info("HTTP/3 server stopped")


# Re-export для удобства тестов: HttpStreamHandler / scope builder.
__all__ = (
    "Http3ServerConfig",
    "HttpStreamHandler",
    "build_http_scope",
    "build_quic_configuration",
    "serve_http3",
)
