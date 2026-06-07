"""Sprint 60 W1 — S-L7-3 fix: GELF socket graceful shutdown tests.

Покрывает sync-путь закрытия persistent UDP/TCP сокетов без event loop.
Ранее (pre-W1) sink.close() был async и требовал живого loop — при
atexit / SIGTERM сокеты оставались открытыми → FD leak под нагрузкой.

Новый метод ``close_sync()`` гарантирует закрытие из любого контекста.
"""

# ruff: noqa: S101, D103, ANN001, ANN201

from __future__ import annotations

import asyncio
import socket
from unittest.mock import patch

import pytest

from src.backend.infrastructure.logging.backends.graylog_gelf import GraylogGelfLogSink


def _make_sink(protocol: str = "udp") -> GraylogGelfLogSink:
    return GraylogGelfLogSink(
        host="127.0.0.1",
        port=12201,
        protocol=protocol,  # type: ignore[arg-type]
        name="test-shutdown",
        connect_timeout=0.5,
        queue_maxsize=10,
    )


# ---------------------------------------------------------------------- close_sync on fresh sink


def test_close_sync_on_fresh_sink_is_safe() -> None:
    """close_sync() на свежем sink (без сокетов) — no-op, no exception."""
    sink = _make_sink("udp")
    assert sink._udp_socket is None
    assert sink._tcp_socket is None
    sink.close_sync()  # не должно бросить
    assert sink._closed is True
    assert sink._udp_socket is None


def test_close_sync_clears_state() -> None:
    sink = _make_sink("udp")
    sink._udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    assert sink._udp_socket is not None
    sink.close_sync()
    assert sink._udp_socket is None
    assert sink._closed is True


def test_close_sync_idempotent() -> None:
    """Повторный close_sync после close() — no-op (idempotent)."""
    sink = _make_sink("udp")
    sink._udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sink.close_sync()
    sink.close_sync()  # второй раз — не должно бросить
    assert sink._udp_socket is None
    assert sink._closed is True


def test_close_sync_tcp_clears_state() -> None:
    sink = _make_sink("tcp")
    sink._tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    assert sink._tcp_socket is not None
    sink.close_sync()
    assert sink._tcp_socket is None


def test_close_sync_handles_oserror_on_close() -> None:
    """Если sock.close() бросает OSError — close_sync проглатывает (best-effort)."""
    sink = _make_sink("udp")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    # Закрываем сокет ДО patch — чтобы close() гарантированно бросил EBADF
    sock.close()
    sink._udp_socket = sock
    # Теперь sock.fileno() == -1, sock.close() бросит OSError
    sink.close_sync()  # не должно бросить наружу
    # _close_sockets сбрасывает атрибут через setattr
    assert sink._udp_socket is None


# ---------------------------------------------------------------------- async close() still works


@pytest.mark.asyncio
async def test_async_close_still_works() -> None:
    """async close() по-прежнему работает (обратная совместимость)."""
    sink = _make_sink("udp")
    await sink.close()
    assert sink._closed is True
    assert sink._udp_socket is None


@pytest.mark.asyncio
async def test_async_close_clears_both_sockets() -> None:
    sink = _make_sink("tcp")
    sink._tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sink._udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    await sink.close()
    assert sink._tcp_socket is None
    assert sink._udp_socket is None


# ---------------------------------------------------------------------- async behavior: no FD leak


def test_close_sync_without_event_loop() -> None:
    """close_sync() работает БЕЗ event loop (sync context, atexit, signal)."""
    sink = _make_sink("udp")
    sink._udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    # не открываем event loop — close_sync должен работать
    sink.close_sync()
    assert sink._udp_socket is None


# ---------------------------------------------------------------------- integration with structlog backend


def test_structlog_backend_shutdown_closes_gelf_sinks() -> None:
    """StructlogGraylogBackend.shutdown() вызывает close_sync на GELF sinks.

    Проверяем, что shutdown правильно вызывает close_sync через SinkRouter.
    """
    from src.backend.infrastructure.logging.structlog_backend import (
        StructlogGraylogBackend,
    )
    from src.backend.infrastructure.logging.router import (
        configure_router,
        reset_router,
    )

    reset_router()  # clean state

    sink = _make_sink("udp")
    sink._udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    configure_router([sink])

    backend = StructlogGraylogBackend()
    backend.shutdown()  # должен вызвать sink.close_sync()

    assert sink._closed is True
    assert sink._udp_socket is None

    reset_router()  # cleanup


def test_structlog_backend_shutdown_no_router() -> None:
    """shutdown() работает даже если router не инициализирован (no-op)."""
    from src.backend.infrastructure.logging.structlog_backend import (
        StructlogGraylogBackend,
    )
    from src.backend.infrastructure.logging.router import reset_router

    reset_router()
    backend = StructlogGraylogBackend()
    backend.shutdown()  # не должно бросить
