"""HTTP-бэкенд антивируса (Wave 2.4).

Тонкая обёртка над уже существующим :class:`AntivirusService` (HTTP API)
из ``infrastructure/external_apis/antivirus.py``. Используется как
fallback, когда ClamAV-бэкенды недоступны (50–500 ms на скан).
"""

from __future__ import annotations

import logging
import time
from typing import Any

from src.core.interfaces.antivirus import AntivirusBackend, AntivirusScanResult

__all__ = ("HttpAntivirusBackend",)

logger = logging.getLogger("infrastructure.antivirus.http")


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
        except Exception:  # noqa: BLE001
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
        except Exception as exc:  # noqa: BLE001
            raise ConnectionError(f"HTTP AV unreachable: {exc}") from exc
        latency_ms = (time.monotonic() - start) * 1000
        clean = bool(verdict.get("clean", False))
        signature = verdict.get("signature") or verdict.get("threat")
        return AntivirusScanResult(
            clean=clean, signature=signature, backend=self.name, latency_ms=latency_ms
        )
