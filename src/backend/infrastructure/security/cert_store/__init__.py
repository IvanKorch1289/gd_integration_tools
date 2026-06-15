"""CertStore package (S55 W1 decomp from cert_store.py 628 LOC).

7 classes decomposed в 7 files:
- ``models.py``: CertEntry (data class)
- ``backend_base.py``: CertBackend (ABC, 4 methods)
- ``backend_memory.py``: MemoryCertBackend
- ``backend_postgres.py``: PostgresCertBackend
- ``backend_vault.py``: VaultCertBackend
- ``backend_mongo.py``: MongoCertBackend
- ``store.py``: CertStore (facade, 10 methods)

Backward-compat: ``from src.backend.infrastructure.security.cert_store import CertStore, MemoryCertBackend`` works.
"""

from __future__ import annotations

from src.backend.infrastructure.security.cert_store.backend_base import (
    CertBackend,  # S55 W1: re-export
)
from src.backend.infrastructure.security.cert_store.backend_memory import (
    MemoryCertBackend,  # S55 W1: re-export
)
from src.backend.infrastructure.security.cert_store.backend_mongo import (
    MongoCertBackend,  # S55 W1: re-export
)
from src.backend.infrastructure.security.cert_store.backend_postgres import (
    PostgresCertBackend,  # S55 W1: re-export
)
from src.backend.infrastructure.security.cert_store.backend_vault import (
    VaultCertBackend,  # S55 W1: re-export
)
from src.backend.core.config.cert_store import cert_store_settings
from src.backend.infrastructure.security.cert_store.models import (
    CertEntry,  # S55 W1: re-export
    _fingerprint,  # S55 W1: re-export
)
from src.backend.infrastructure.security.cert_store.store import (
    CertStore,  # S55 W1: re-export
)

__all__ = (
    "CertEntry",
    "CertBackend",
    "MemoryCertBackend",
    "PostgresCertBackend",
    "VaultCertBackend",
    "MongoCertBackend",
    "CertStore",
    "_fingerprint",
    "create_cert_store",
)


# --- Top-level re-exports (S55 W1 decomp: preserve original public surface) ---

def create_cert_store() -> CertStore:
    """Фабрика по умолчанию — собирает store из глобальных настроек."""
    return CertStore.from_settings(cert_store_settings)
