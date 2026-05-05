"""Бэкенды AntivirusBackend ABC (Wave 2.4)."""

from src.backend.infrastructure.antivirus.backends.clamav_tcp import ClamAVTcpBackend
from src.backend.infrastructure.antivirus.backends.clamav_unix import ClamAVUnixBackend
from src.backend.infrastructure.antivirus.backends.http import HttpAntivirusBackend

__all__ = ("ClamAVUnixBackend", "ClamAVTcpBackend", "HttpAntivirusBackend")
