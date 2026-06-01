"""ClamAV через unix socket (Wave 2.4).

Самый быстрый путь — 2–5 ms на сканирование, без TCP-overhead.

Протокол INSTREAM:

    1. Send ``zINSTREAM\\0`` to the socket.
    2. Send ``<chunk_size_be32><chunk_data>`` repeatedly.
    3. Send ``<0_be32>`` as terminator.
    4. Read response: ``stream: OK\\0`` или ``stream: <SIG> FOUND\\0``.

Использовать только в окружениях, где clamd доступен через unix socket
(обычно ``/var/run/clamav/clamd.ctl``).
"""

from __future__ import annotations

import asyncio
import logging
import struct
import time
from pathlib import Path

from src.backend.core.interfaces.antivirus import AntivirusBackend, AntivirusScanResult

__all__ = ("ClamAVUnixBackend",)

logger = logging.getLogger("infrastructure.antivirus.clamav_unix")

_CHUNK_SIZE = 64 * 1024  # 64 KiB


class ClamAVUnixBackend(AntivirusBackend):
    """ClamAV INSTREAM поверх unix socket."""

    name = "clamav_unix"

    def __init__(
        self, socket_path: str = "/var/run/clamav/clamd.ctl", timeout: float = 30.0
    ) -> None:
        self._socket_path = socket_path
        self._timeout = timeout

    async def is_available(self) -> bool:
        if not Path(self._socket_path).exists():
            return False
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_unix_connection(self._socket_path), timeout=2.0
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
                asyncio.open_unix_connection(self._socket_path), timeout=self._timeout
            )
        except (OSError, asyncio.TimeoutError) as exc:
            raise ConnectionError(f"ClamAV unix socket недоступен: {exc}") from exc

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


def _parse_clamav_response(
    response: bytes, *, backend: str, latency_ms: float
) -> AntivirusScanResult:
    text = response.rstrip(b"\0").decode("utf-8", errors="replace").strip()
    if text.endswith("OK"):
        return AntivirusScanResult(
            clean=True, signature=None, backend=backend, latency_ms=latency_ms
        )
    if text.endswith(" FOUND"):
        sig = text.split(":", 1)[1].strip().rsplit(" FOUND", 1)[0].strip()
        return AntivirusScanResult(
            clean=False, signature=sig, backend=backend, latency_ms=latency_ms
        )
    raise RuntimeError(f"ClamAV unexpected response: {text!r}")
