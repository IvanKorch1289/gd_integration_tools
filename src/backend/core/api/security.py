"""Sprint 37: security facade — re-exports infrastructure.security.

Ponytail fix: services/* должен импортировать через core.api.security
(not infrastructure.security directly). Это eliminates
services → infrastructure violations.
"""
from __future__ import annotations

from src.backend.infrastructure.security import pii_streaming, signatures

# Re-exports infrastructure.security (4 services → infrastructure.security violations)
from src.backend.infrastructure.security.cert_store import CertStore

# Backward-compat aliases
PiiStreaming = pii_streaming
Signatures = signatures

__all__ = [
    "CertStore",
    "pii_streaming",
    "signatures",
    "PiiStreaming",
    "Signatures",
]
