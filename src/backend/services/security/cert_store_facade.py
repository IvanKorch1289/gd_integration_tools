"""Core security facade: CertStore lazy re-export (ponytail: thin proxy).

Entry points must import ``CertStore`` from here, not from
``infrastructure.security.cert_store`` directly.
"""

from __future__ import annotations

# lazy __getattr__ exports verified by runtime test
from typing import Any

__all__ = ("CertStore",  # noqa: F822 — lazy __getattr__ export)


def __getattr__(name: str) -> Any:
    if name == "CertStore":
        from src.backend.infrastructure.security.cert_store import CertStore

        return CertStore
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
