"""HTTP-бэкенд антивируса (Wave 2.4 + Sprint 0 dedup).

Тонкая обёртка над :class:`AntivirusService` (HTTP API) из
``infrastructure/antivirus/service.py``. Используется как fallback,
когда ClamAV-бэкенды недоступны (50–500 ms на скан).
"""

from __future__ import annotations

import time
from typing import Any

from src.backend.core.interfaces.antivirus import AntivirusBackend, AntivirusScanResult
from src.backend.infrastructure.logging.factory import get_logger

__all__ = ("HttpAntivirusBackend",)

logger = get_logger("infrastructure.antivirus.http")


class HttpAntivirusBackend(AntivirusBackend):
    """Адаптер :class:`AntivirusService` под :class:`AntivirusBackend`."""

    name = "http"

    def __init__(self, service: Any) -> None:
        self._service = service

    async def is_available(self) -> bool:
        check = getattr(self._service, "ping", None)
        if check is None:
            return True  # сервис не объявляет ping — считаем доступным
        try:
            return bool(await check())
        except Exception as _:
            return False

    async def scan_bytes(self, payload: bytes) -> AntivirusScanResult:
        start = time.monotonic()
        scan_fn = getattr(self._service, "scan_bytes", None) or getattr(
            self._service, "scan_payload", None
        )
        if scan_fn is None:
            raise RuntimeError(
                "HTTP AntivirusService не имеет метода scan_bytes/scan_payload"
            )
        try:
            verdict = await scan_fn(payload)
        except Exception as exc:
            raise ConnectionError(f"HTTP AV unreachable: {exc}") from exc
        latency_ms = (time.monotonic() - start) * 1000
        clean = bool(verdict.get("clean", False))
        signature = verdict.get("signature") or verdict.get("threat")
        return AntivirusScanResult(
            clean=clean, signature=signature, backend=self.name, latency_ms=latency_ms
        )
