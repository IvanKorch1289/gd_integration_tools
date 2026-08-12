"""HTTP-бэкенд антивируса (Wave 2.4 + Sprint 0 dedup).

Тонкая обёртка над :class:`AntivirusService` (HTTP API) из
``infrastructure/antivirus/service.py``. Используется как fallback,
когда ClamAV-бэкенды недоступны (50–500 ms на скан).
"""

from __future__ import annotations

import logging
import time
from typing import Any

from src.backend.core.interfaces.antivirus import AntivirusBackend, AntivirusScanResult

logger = logging.getLogger(__name__)

__all__ = ("HttpAntivirusBackend",)



class HttpAntivirusBackend(AntivirusBackend):
    """Адаптер :class:`AntivirusService` под :class:`AntivirusBackend`."""

    name = "http"

    def __init__(self, service: Any) -> None:
        self._service = service

    async def is_available(self) -> bool:
        """Метод is_available (см. signature)."""
        check = getattr(self._service, "ping", None)
        if check is None:
            return True  # сервис не объявляет ping — считаем доступным
        try:
            return bool(await check())
        except (ConnectionError, TimeoutError, OSError) as exc:
            # D-AUDIT-15101 fix (cycle 151): narrow от bare
            # 'except Exception: _' (swallow'ил SystemExit/KeyboardInterrupt
            # + unexpected exceptions) до конкретных network-related
            # exceptions. AV HTTP ping может fail с:
            # - ConnectionError: HTTP service down
            # - TimeoutError: request timeout
            # - OSError: socket/network errors
            # Soft-fail behavior сохранён (return False → AV unavailable).
            logger.debug(
                "antivirus.http.is_available: ping failed (exc_type=%s "
                "exc_msg=%s) — AV unavailable",
                type(exc).__name__, exc,
            )
            return False

    async def scan_bytes(self, payload: bytes) -> AntivirusScanResult:
        """Метод scan_bytes (см. signature)."""
        start = time.monotonic()
        scan_fn = getattr(self._service, "scan_bytes", None) or getattr(
            self._service, "scan_payload", None,
        )
        if scan_fn is None:
            raise RuntimeError(
                "HTTP AntivirusService не имеет метода scan_bytes/scan_payload",
            )
        try:
            verdict = await scan_fn(payload)
        except Exception as exc:
            raise ConnectionError(f"HTTP AV unreachable: {exc}") from exc
        latency_ms = (time.monotonic() - start) * 1000
        clean = bool(verdict.get("clean", False))
        signature = verdict.get("signature") or verdict.get("threat")
        return AntivirusScanResult(
            clean=clean, signature=signature, backend=self.name, latency_ms=latency_ms,
        )
