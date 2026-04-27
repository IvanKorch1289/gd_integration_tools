"""Бэкенды AntivirusBackend ABC (Wave 2.4)."""

from src.infrastructure.antivirus.backends.clamav_tcp import ClamAVTcpBackend
from src.infrastructure.antivirus.backends.clamav_unix import ClamAVUnixBackend
from src.infrastructure.antivirus.backends.http import HttpAntivirusBackend

__all__ = ("ClamAVUnixBackend", "ClamAVTcpBackend", "HttpAntivirusBackend")
