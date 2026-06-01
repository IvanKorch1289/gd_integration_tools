"""ABC ``AntivirusBackend`` — пер-бэкендная абстракция AV-сканера.

Wave 1.1: контракт для будущих ClamAV (unix socket / TCP) и HTTP-fallback
бэкендов в ``infrastructure/antivirus/`` (Wave 2.4). Hash-кэш реализуется
поверх как декоратор, не часть ABC.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(slots=True)
class AntivirusScanResult:
    """Результат сканирования.

    Атрибуты:
        clean: True — файл чистый; False — найдена угроза.
        signature: Имя обнаруженной сигнатуры (None, если ``clean``).
        backend: Имя бэкенда, выполнившего сканирование.
        latency_ms: Время сканирования в миллисекундах.
    """

    clean: bool
    signature: str | None = None
    backend: str = ""
    latency_ms: float | None = None


class AntivirusBackend(ABC):
    """Абстракция AV-сканера (ClamAV unix socket, ClamAV TCP, HTTP)."""

    name: str = "base"

    @abstractmethod
    async def scan_bytes(self, payload: bytes) -> AntivirusScanResult:
        """Сканирует байтовый поток.

        Returns:
            AntivirusScanResult с флагом ``clean`` и опциональной сигнатурой.

        Raises:
            ConnectionError: бэкенд недоступен (вызывающая сторона решает,
                использовать fallback или эскалировать ошибку).
        """

    @abstractmethod
    async def is_available(self) -> bool:
        """Быстрая проверка доступности бэкенда (для health-check / fallback)."""
