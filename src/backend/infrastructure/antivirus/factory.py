"""Фабрика AntivirusBackend (Wave 2.4).

Собирает backend по конфигу + опционально оборачивает hash-кэшем.
Если активный backend недоступен (``is_available() == False``), фабрика
автоматически выбирает следующий по порядку: clamav_unix → clamav_tcp →
http.
"""

from __future__ import annotations

import logging
from typing import Iterable

from src.backend.core.interfaces.antivirus import AntivirusBackend, AntivirusScanResult

__all__ = ("ChainedAntivirusBackend", "create_antivirus_backend")

logger = logging.getLogger("infrastructure.antivirus.factory")


class ChainedAntivirusBackend(AntivirusBackend):
    """Последовательно опрашивает backends; первый доступный выполняет скан."""

    name = "chained"

    def __init__(self, backends: Iterable[AntivirusBackend]) -> None:
        self._backends = list(backends)

    async def is_available(self) -> bool:
        for backend in self._backends:
            if await backend.is_available():
                return True
        return False

    async def scan_bytes(self, payload: bytes) -> AntivirusScanResult:
        last_error: Exception | None = None
        for backend in self._backends:
            try:
                if not await backend.is_available():
                    continue
                return await backend.scan_bytes(payload)
            except ConnectionError as exc:
                last_error = exc
                logger.warning(
                    "AV backend %s unavailable, trying next: %s", backend.name, exc
                )
                continue
        if last_error is not None:
            raise last_error
        raise ConnectionError("Ни один AV-бэкенд недоступен")


def create_antivirus_backend() -> AntivirusBackend:
    """Создаёт ChainedAntivirusBackend с дефолтным порядком.

    Порядок: ClamAV unix → ClamAV TCP → HTTP-сервис. Hash-кэш оборачивается
    отдельно вызывающей стороной (см. ``AntivirusHashCache``).
    """
    from src.backend.infrastructure.antivirus.backends.clamav_tcp import (
        ClamAVTcpBackend,
    )
    from src.backend.infrastructure.antivirus.backends.clamav_unix import (
        ClamAVUnixBackend,
    )
    from src.backend.infrastructure.antivirus.backends.http import HttpAntivirusBackend

    backends: list[AntivirusBackend] = [ClamAVUnixBackend(), ClamAVTcpBackend()]
    try:
        from src.backend.infrastructure.antivirus.service import get_antivirus_service

        backends.append(HttpAntivirusBackend(service=get_antivirus_service()))
    except Exception as exc:  # noqa: BLE001
        logger.debug("HTTP AV backend skipped: %s", exc)
    return ChainedAntivirusBackend(backends)
