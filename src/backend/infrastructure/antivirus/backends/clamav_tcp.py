"""ClamAV INSTREAM через TCP (Wave 2.4).

Используется, когда unix socket недоступен (например, кросс-нодовая
кластеризация). Протокол идентичен unix-версии.
"""

from __future__ import annotations

import asyncio
import logging
import struct
import time

from src.backend.core.interfaces.antivirus import AntivirusBackend, AntivirusScanResult
from src.backend.infrastructure.antivirus.backends.clamav_unix import (
    _parse_clamav_response,
)

__all__ = ("ClamAVTcpBackend",)

logger = logging.getLogger("infrastructure.antivirus.clamav_tcp")

_CHUNK_SIZE = 64 * 1024


class ClamAVTcpBackend(AntivirusBackend):
    """ClamAV INSTREAM поверх TCP."""

    name = "clamav_tcp"

    def __init__(
        self, host: str = "127.0.0.1", port: int = 3310, timeout: float = 30.0
    ) -> None:
        self._host = host
        self._port = port
        self._timeout = timeout

    async def is_available(self) -> bool:
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, self._port), timeout=2.0
            )
        except OSError, asyncio.TimeoutError:
            return False
        try:
            writer.write(b"zPING\0")
            await writer.drain()
            data = await asyncio.wait_for(reader.read(64), timeout=2.0)
            return b"PONG" in data
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:  # noqa: BLE001, S110 — closing socket, error не критичен
                pass

    async def scan_bytes(self, payload: bytes) -> AntivirusScanResult:
        start = time.monotonic()
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, self._port), timeout=self._timeout
            )
        except (OSError, asyncio.TimeoutError) as exc:
            raise ConnectionError(
                f"ClamAV TCP {self._host}:{self._port} недоступен: {exc}"
            ) from exc

        try:
            writer.write(b"zINSTREAM\0")
            for chunk_start in range(0, len(payload), _CHUNK_SIZE):
                chunk = payload[chunk_start : chunk_start + _CHUNK_SIZE]
                writer.write(struct.pack(">I", len(chunk)) + chunk)
            writer.write(struct.pack(">I", 0))
            await writer.drain()

            response = await asyncio.wait_for(reader.read(4096), timeout=self._timeout)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:  # noqa: BLE001, S110 — closing socket, error не критичен
                pass

        latency_ms = (time.monotonic() - start) * 1000
        return _parse_clamav_response(
            response, backend=self.name, latency_ms=latency_ms
        )
