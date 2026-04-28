"""Unit-тесты антивирусных backend'ов.

Покрывает:

* :class:`HttpAntivirusBackend` — обёртку над external-AV-сервисом
  (mock-сервис с методами ``ping`` / ``scan_bytes``);
* :class:`ClamAVUnixBackend` и :class:`ClamAVTcpBackend` — INSTREAM
  через ``asyncio.open_unix_connection`` / ``asyncio.open_connection``
  c monkeypatch'ом stream-ридера/райтера;
* parsing ClamAV-ответа: ``stream: OK`` / ``stream: <SIG> FOUND``;
* fallback-сценарий ``ConnectionError`` при недоступном backend'е.

Реальная сеть и реальный clamd не требуются.
"""

# ruff: noqa: S101  # assert — стандартная идиома pytest

from __future__ import annotations

import asyncio
import struct
from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.core.interfaces.antivirus import AntivirusScanResult
from src.infrastructure.antivirus.backends.clamav_tcp import ClamAVTcpBackend
from src.infrastructure.antivirus.backends.clamav_unix import (
    ClamAVUnixBackend,
    _parse_clamav_response,
)
from src.infrastructure.antivirus.backends.http import HttpAntivirusBackend

# ── HttpAntivirusBackend ───────────────────────────────────────────────────


class _FakeHttpService:
    """Минимальный fake внешнего AV-сервиса с ``ping`` / ``scan_bytes``."""

    def __init__(
        self,
        *,
        ping_ok: bool = True,
        verdict: dict[str, Any] | None = None,
        raise_on_scan: Exception | None = None,
    ) -> None:
        self._ping_ok = ping_ok
        self._verdict = verdict or {"clean": True}
        self._raise = raise_on_scan
        self.calls: list[bytes] = []

    async def ping(self) -> bool:
        return self._ping_ok

    async def scan_bytes(self, payload: bytes) -> dict[str, Any]:
        self.calls.append(payload)
        if self._raise is not None:
            raise self._raise
        return self._verdict


async def test_http_backend_clean_verdict() -> None:
    """``scan_bytes`` маппит ``clean=True`` из ответа сервиса."""
    service = _FakeHttpService(verdict={"clean": True})
    backend = HttpAntivirusBackend(service)

    result = await backend.scan_bytes(b"some bytes")

    assert isinstance(result, AntivirusScanResult)
    assert result.clean is True
    assert result.signature is None
    assert result.backend == "http"
    assert result.latency_ms is not None and result.latency_ms >= 0
    assert service.calls == [b"some bytes"]


async def test_http_backend_threat_verdict_with_signature() -> None:
    """``signature`` извлекается из ответа сервиса."""
    service = _FakeHttpService(
        verdict={"clean": False, "signature": "Eicar-Test"}
    )
    backend = HttpAntivirusBackend(service)

    result = await backend.scan_bytes(b"X")
    assert result.clean is False
    assert result.signature == "Eicar-Test"


async def test_http_backend_threat_verdict_via_threat_field() -> None:
    """Если сервис вместо ``signature`` отдаёт ``threat`` — это валидно."""
    service = _FakeHttpService(verdict={"clean": False, "threat": "Trojan.X"})
    backend = HttpAntivirusBackend(service)

    result = await backend.scan_bytes(b"X")
    assert result.clean is False
    assert result.signature == "Trojan.X"


async def test_http_backend_is_available_uses_ping() -> None:
    """``is_available`` отдаёт ``True``, если ``ping`` -> ``True``."""
    backend = HttpAntivirusBackend(_FakeHttpService(ping_ok=True))
    assert await backend.is_available() is True

    backend2 = HttpAntivirusBackend(_FakeHttpService(ping_ok=False))
    assert await backend2.is_available() is False


async def test_http_backend_is_available_without_ping_returns_true() -> None:
    """Если у сервиса нет ``ping`` — backend оптимистично доступен."""

    class _NoPing:
        async def scan_bytes(self, _: bytes) -> dict[str, Any]:
            return {"clean": True}

    backend = HttpAntivirusBackend(_NoPing())
    assert await backend.is_available() is True


async def test_http_backend_scan_raises_connection_error_on_failure() -> None:
    """Любая ошибка сервиса при ``scan_bytes`` -> ``ConnectionError``."""
    service = _FakeHttpService(raise_on_scan=RuntimeError("boom"))
    backend = HttpAntivirusBackend(service)

    with pytest.raises(ConnectionError):
        await backend.scan_bytes(b"x")


async def test_http_backend_without_scan_method_raises_runtime_error() -> None:
    """Если сервис не реализует ни ``scan_bytes``, ни ``scan_payload`` -> RuntimeError."""

    class _Empty:
        async def ping(self) -> bool:
            return True

    backend = HttpAntivirusBackend(_Empty())
    with pytest.raises(RuntimeError):
        await backend.scan_bytes(b"x")


# ── ClamAV response parser ─────────────────────────────────────────────────


def test_parse_clamav_clean_response() -> None:
    """``stream: OK`` -> clean-вердикт без сигнатуры."""
    result = _parse_clamav_response(
        b"stream: OK\0", backend="clamav_unix", latency_ms=1.0
    )
    assert result.clean is True
    assert result.signature is None
    assert result.backend == "clamav_unix"


def test_parse_clamav_threat_response() -> None:
    """``stream: <SIG> FOUND`` -> threat-вердикт с сигнатурой."""
    result = _parse_clamav_response(
        b"stream: Win.Test.EICAR_HDB-1 FOUND\0",
        backend="clamav_tcp",
        latency_ms=2.0,
    )
    assert result.clean is False
    assert result.signature == "Win.Test.EICAR_HDB-1"
    assert result.backend == "clamav_tcp"


def test_parse_clamav_unexpected_response_raises() -> None:
    """Неожиданный ответ ClamAV -> ``RuntimeError``."""
    with pytest.raises(RuntimeError):
        _parse_clamav_response(
            b"weird payload", backend="clamav_unix", latency_ms=1.0
        )


# ── ClamAV unix/TCP scan_bytes via stream mocks ────────────────────────────


class _FakeWriter:
    """Имитирует ``asyncio.StreamWriter`` — собирает записанные байты."""

    def __init__(self) -> None:
        self.buffer = bytearray()
        self.closed = False

    def write(self, data: bytes) -> None:
        self.buffer.extend(data)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


class _FakeReader:
    """Имитирует ``asyncio.StreamReader`` с заданным ответом."""

    def __init__(self, response: bytes) -> None:
        self._response = response

    async def read(self, _n: int) -> bytes:
        return self._response


@pytest.fixture
def fake_streams() -> tuple[_FakeReader, _FakeWriter]:
    """Reader+Writer пара с дефолтным OK-ответом."""
    return _FakeReader(b"stream: OK\0"), _FakeWriter()


async def test_clamav_unix_scan_bytes_clean(
    monkeypatch: pytest.MonkeyPatch,
    fake_streams: tuple[_FakeReader, _FakeWriter],
    tmp_path: Any,
) -> None:
    """``scan_bytes`` поверх unix socket: OK-ответ -> clean."""
    reader, writer = fake_streams

    async def _open(_path: str) -> tuple[_FakeReader, _FakeWriter]:
        return reader, writer

    monkeypatch.setattr(asyncio, "open_unix_connection", _open)

    backend = ClamAVUnixBackend(socket_path=str(tmp_path / "fake.sock"))
    result = await backend.scan_bytes(b"abc")

    assert result.clean is True
    assert result.backend == "clamav_unix"
    # Должны быть записаны: zINSTREAM\0 + (size_be32 + payload) + 0_be32 терминатор
    assert writer.buffer.startswith(b"zINSTREAM\0")
    assert writer.buffer.endswith(struct.pack(">I", 0))
    assert writer.closed is True


async def test_clamav_unix_scan_bytes_threat(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """``scan_bytes`` поверх unix socket: FOUND-ответ -> threat + signature."""
    reader = _FakeReader(b"stream: Eicar-Signature FOUND\0")
    writer = _FakeWriter()

    async def _open(_path: str) -> tuple[_FakeReader, _FakeWriter]:
        return reader, writer

    monkeypatch.setattr(asyncio, "open_unix_connection", _open)

    backend = ClamAVUnixBackend(socket_path=str(tmp_path / "fake.sock"))
    result = await backend.scan_bytes(b"infected")

    assert result.clean is False
    assert result.signature == "Eicar-Signature"


async def test_clamav_unix_scan_raises_connection_error_when_socket_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """Если ``open_unix_connection`` падает — поднимается ``ConnectionError``."""

    async def _fail(_path: str) -> tuple[_FakeReader, _FakeWriter]:
        raise OSError("no socket")

    monkeypatch.setattr(asyncio, "open_unix_connection", _fail)

    backend = ClamAVUnixBackend(socket_path=str(tmp_path / "missing.sock"))
    with pytest.raises(ConnectionError):
        await backend.scan_bytes(b"x")


async def test_clamav_unix_is_available_false_when_no_socket(
    tmp_path: Any,
) -> None:
    """``is_available`` -> ``False``, если файла сокета нет."""
    backend = ClamAVUnixBackend(socket_path=str(tmp_path / "no.sock"))
    assert await backend.is_available() is False


async def test_clamav_tcp_scan_bytes_clean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``scan_bytes`` поверх TCP: OK-ответ -> clean."""
    reader = _FakeReader(b"stream: OK\0")
    writer = _FakeWriter()

    async def _open(_host: str, _port: int) -> tuple[_FakeReader, _FakeWriter]:
        return reader, writer

    monkeypatch.setattr(asyncio, "open_connection", _open)

    backend = ClamAVTcpBackend(host="127.0.0.1", port=3310)
    result = await backend.scan_bytes(b"abc")
    assert result.clean is True
    assert result.backend == "clamav_tcp"


async def test_clamav_tcp_is_available_pong(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``is_available`` -> ``True``, если ClamAV отвечает ``PONG``."""
    reader = _FakeReader(b"PONG\0")
    writer = _FakeWriter()

    async def _open(_host: str, _port: int) -> tuple[_FakeReader, _FakeWriter]:
        return reader, writer

    monkeypatch.setattr(asyncio, "open_connection", _open)

    backend = ClamAVTcpBackend(host="127.0.0.1", port=3310)
    assert await backend.is_available() is True


async def test_clamav_tcp_is_available_false_on_oserror(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``is_available`` -> ``False``, если open_connection падает."""

    async def _fail(_host: str, _port: int) -> tuple[_FakeReader, _FakeWriter]:
        raise OSError("connection refused")

    monkeypatch.setattr(asyncio, "open_connection", _fail)

    backend = ClamAVTcpBackend(host="127.0.0.1", port=3310)
    assert await backend.is_available() is False


async def test_clamav_tcp_scan_raises_connection_error_when_host_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Падение ``open_connection`` при ``scan_bytes`` -> ``ConnectionError``."""

    async def _fail(_host: str, _port: int) -> tuple[_FakeReader, _FakeWriter]:
        raise OSError("unreachable")

    monkeypatch.setattr(asyncio, "open_connection", _fail)

    backend = ClamAVTcpBackend(host="127.0.0.1", port=3310)
    with pytest.raises(ConnectionError):
        await backend.scan_bytes(b"x")


# ── Optional respx integration (если установлен) ───────────────────────────


def test_respx_is_optional() -> None:
    """``respx`` не требуется для прохождения этого набора."""
    respx = pytest.importorskip("respx", reason="respx не установлен — пропускаем")
    # Если respx есть, проверим, что mock-transport фактически собирается.
    assert hasattr(respx, "mock")


# ── AsyncMock-based smoke ──────────────────────────────────────────────────


async def test_http_backend_with_async_mock_service() -> None:
    """``HttpAntivirusBackend`` корректно работает с ``AsyncMock``-сервисом."""
    service = AsyncMock()
    service.ping.return_value = True
    service.scan_bytes.return_value = {"clean": True}

    backend = HttpAntivirusBackend(service)
    assert await backend.is_available() is True

    result = await backend.scan_bytes(b"data")
    assert result.clean is True
    service.scan_bytes.assert_awaited_once_with(b"data")
