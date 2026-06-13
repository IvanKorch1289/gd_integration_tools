"""Sprint 60 W1 — E2E: structlog → Graylog GELF integration tests.

Покрывает полный pipeline:
1. structlog config (через StructlogGraylogBackend.configure)
2. logger.info("msg %s", arg) → compat shim → structlog → JSON render
3. route_to_sinks → GraylogGelfLogSink → GELF UDP packet
4. UDP server принимает пакет → парсим GELF → проверяем поля
"""

# ruff: noqa: S101, D103, ANN001, ANN201

from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from typing import Any

import pytest

from src.backend.infrastructure.logging.factory import (
    configure_logging,
    get_logger,
    shutdown_logging,
)
from src.backend.infrastructure.logging.router import configure_router, reset_router
from src.backend.infrastructure.logging.structlog_backend import (
    StructlogGraylogBackend,
    StructlogLogger,
)

# ---------------------------------------------------------------------- helper: UDP server


class _MockGraylogServer:
    """Минимальный UDP-сервер, принимающий GELF пакеты."""

    def __init__(self, port: int = 0) -> None:
        self.port = port
        self.received: list[dict[str, Any]] = []
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind(("127.0.0.1", self.port))
        self.port = self._sock.getsockname()[1]
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        time.sleep(0.05)  # let server start

    def stop(self) -> None:
        self._stop.set()
        if self._sock is not None:
            self._sock.close()
        if self._thread is not None:
            self._thread.join(timeout=1.0)

    def _loop(self) -> None:
        assert self._sock is not None
        while not self._stop.is_set():
            try:
                self._sock.settimeout(0.1)
                data, _ = self._sock.recvfrom(65535)
                try:
                    self.received.append(json.loads(data))
                except json.JSONDecodeError:
                    pass
            except (TimeoutError, OSError):
                continue


@pytest.fixture
def mock_graylog() -> Any:
    server = _MockGraylogServer()
    server.start()
    yield server
    server.stop()


# ---------------------------------------------------------------------- e2e: factory → structlog


def test_factory_default_is_structlog() -> None:
    """factory.configure_logging() без аргументов → structlog backend."""
    backend = configure_logging()
    assert isinstance(backend, StructlogGraylogBackend)
    shutdown_logging()


def test_get_logger_returns_structlog_logger() -> None:
    """get_logger() возвращает StructlogLogger (default backend)."""
    configure_logging()
    logger = get_logger("test-app")
    assert isinstance(logger, StructlogLogger)
    shutdown_logging()


# ---------------------------------------------------------------------- e2e: pipe to mock GELF


@pytest.mark.asyncio
async def test_log_flows_to_graylog_gelf(mock_graylog: _MockGraylogServer) -> None:
    """logger.info() → structlog → GELF UDP → mock server получает пакет."""
    reset_router()

    # Configure structlog backend (without Graylog handler — we add our own sink)
    configure_logging()  # default = structlog

    # Configure router with our mock as Graylog target
    from src.backend.infrastructure.logging.backends.graylog_gelf import (
        GraylogGelfLogSink,
    )

    sink = GraylogGelfLogSink(
        host="127.0.0.1",
        port=mock_graylog.port,
        protocol="udp",
        name="e2e-test",
        compress=False,
    )
    configure_router([sink])

    logger = get_logger("e2e")
    logger.info("Hello %s from %s", "world", "pytest")

    # Wait for async write + drain
    await asyncio.sleep(0.5)
    await sink.close()

    shutdown_logging()
    reset_router()

    assert len(mock_graylog.received) >= 1
    last = mock_graylog.received[-1]
    assert "Hello world from pytest" in last.get("short_message", "")
    assert last.get("version") == "1.1"
    assert last.get("host")  # hostname set


@pytest.mark.asyncio
async def test_log_with_kwargs_appears_as_gelf_additional_field(
    mock_graylog: _MockGraylogServer,
) -> None:
    """logger.info("msg", key=val) → GELF additional field ``_key``."""
    reset_router()
    configure_logging()

    from src.backend.infrastructure.logging.backends.graylog_gelf import (
        GraylogGelfLogSink,
    )

    sink = GraylogGelfLogSink(
        host="127.0.0.1",
        port=mock_graylog.port,
        protocol="udp",
        name="e2e-kwargs",
        compress=False,
    )
    configure_router([sink])

    logger = get_logger("e2e-kw")
    logger.info("Order created", order_id=123, tenant_id="t-1")

    await asyncio.sleep(0.5)
    await sink.close()

    shutdown_logging()
    reset_router()

    assert len(mock_graylog.received) >= 1
    last = mock_graylog.received[-1]
    assert last.get("_order_id") == 123
    assert last.get("_tenant_id") == "t-1"


# ---------------------------------------------------------------------- e2e: compat shim end-to-end


@pytest.mark.asyncio
async def test_compat_shim_with_positional_args_in_gelf(
    mock_graylog: _MockGraylogServer,
) -> None:
    """stdlib-style %-formatting в GELF (фикс S59 W2 lesson)."""
    reset_router()
    configure_logging()

    from src.backend.infrastructure.logging.backends.graylog_gelf import (
        GraylogGelfLogSink,
    )

    sink = GraylogGelfLogSink(
        host="127.0.0.1",
        port=mock_graylog.port,
        protocol="udp",
        name="e2e-compat",
        compress=False,
    )
    configure_router([sink])

    logger = get_logger("e2e-compat")
    logger.warning(
        "User %s failed login from %s (attempt %d)", "alice", "192.168.1.1", 3
    )

    await asyncio.sleep(0.5)
    await sink.close()

    shutdown_logging()
    reset_router()

    assert len(mock_graylog.received) >= 1
    last = mock_graylog.received[-1]
    assert "User alice failed login from 192.168.1.1 (attempt 3)" in last.get(
        "short_message", ""
    )
    assert last.get("level") == 4  # syslog warning


# ---------------------------------------------------------------------- e2e: shutdown clears FDs


def test_shutdown_does_not_leak_fds(mock_graylog: _MockGraylogServer) -> None:
    """После backend.shutdown() сокеты закрыты → FD не растут."""
    import psutil

    reset_router()
    configure_logging()

    from src.backend.infrastructure.logging.backends.graylog_gelf import (
        GraylogGelfLogSink,
    )

    sink = GraylogGelfLogSink(
        host="127.0.0.1",
        port=mock_graylog.port,
        protocol="udp",
        name="e2e-fd",
        compress=False,
    )
    configure_router([sink])

    logger = get_logger("e2e-fd")
    proc = psutil.Process()
    fds_before = proc.num_fds() if hasattr(proc, "num_fds") else 0

    # 10 log writes → создаст/переиспользует 1 UDP socket
    for i in range(10):
        logger.info("log %s", i)

    time.sleep(0.3)

    # sync shutdown — должен закрыть все сокеты
    shutdown_logging()  # это → backend.shutdown() → sink.close_sync()
    reset_router()

    if fds_before:
        fds_after = proc.num_fds()
        # Не должно быть роста FD (допуск: ±2 на sysctl-флуктуации)
        assert fds_after <= fds_before + 2, (
            f"FD leak detected: before={fds_before}, after={fds_after}"
        )
