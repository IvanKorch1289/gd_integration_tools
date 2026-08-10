"""Бэкенды AntivirusBackend ABC (Wave 2.4)."""

from src.backend.infrastructure.antivirus.backends.clamav_tcp import (
    ClamAVTcpBackend,  # noqa: F401 — re-export
)
from src.backend.infrastructure.antivirus.backends.clamav_unix import (
    ClamAVUnixBackend,  # noqa: F401 — re-export
)
from src.backend.infrastructure.antivirus.backends.http import (
    HttpAntivirusBackend,  # noqa: F401 — re-export
)

__all__ = ("ClamAVTcpBackend", "ClamAVUnixBackend", "HttpAntivirusBackend")
