"""Антивирусная подсистема (Wave 2.4).

Модули:

* :mod:`infrastructure.antivirus.backends` — реализации
  :class:`core.interfaces.AntivirusBackend` (ClamAV unix-socket, ClamAV TCP,
  HTTP fallback);
* :mod:`infrastructure.antivirus.hash_cache` — SHA-256 кэш вердиктов
  поверх Redis (короткий TTL, key prefix ``antivirus:hash:*``);
* :mod:`infrastructure.antivirus.factory` — выбор бэкенда по конфигу +
  сборка цепочки fallback.
"""

from src.infrastructure.antivirus.backends.clamav_tcp import ClamAVTcpBackend
from src.infrastructure.antivirus.backends.clamav_unix import ClamAVUnixBackend
from src.infrastructure.antivirus.backends.http import HttpAntivirusBackend
from src.infrastructure.antivirus.factory import create_antivirus_backend
from src.infrastructure.antivirus.hash_cache import AntivirusHashCache

__all__ = (
    "ClamAVUnixBackend",
    "ClamAVTcpBackend",
    "HttpAntivirusBackend",
    "AntivirusHashCache",
    "create_antivirus_backend",
)
