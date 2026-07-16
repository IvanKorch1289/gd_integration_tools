"""Core security facade: CertStore lazy re-export (ponytail: thin proxy).

Entry points must import ``CertStore`` from here, not from
``infrastructure.security.cert_store`` directly.
"""

from __future__ import annotations

from typing import Any

__all__ = ("CertStore",)


def __getattr__(name: str) -> Any:
    if name == "CertStore":
        from src.backend.infrastructure.security.cert_store import CertStore

        return CertStore
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
