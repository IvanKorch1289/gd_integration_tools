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

from src.backend.core.config.cert_store import (  # noqa: F401 — re-export
    cert_store_settings as cert_store_settings,
)
from src.backend.infrastructure.security.cert_store.backend_base import (  # noqa: F401 — re-export
    CertBackend,  # S55 W1: re-export
)
from src.backend.infrastructure.security.cert_store.backend_memory import (  # noqa: F401 — re-export
    MemoryCertBackend,  # S55 W1: re-export
)
from src.backend.infrastructure.security.cert_store.backend_mongo import (  # noqa: F401 — re-export
    MongoCertBackend,  # S55 W1: re-export
)
from src.backend.infrastructure.security.cert_store.backend_postgres import (  # noqa: F401 — re-export
    PostgresCertBackend,  # S55 W1: re-export
)
from src.backend.infrastructure.security.cert_store.backend_vault import (  # noqa: F401 — re-export
    VaultCertBackend,  # S55 W1: re-export
)
from src.backend.infrastructure.security.cert_store.models import (  # noqa: F401 — re-export
    CertEntry,  # S55 W1: re-export
    _fingerprint,  # S55 W1: re-export
)
from src.backend.infrastructure.security.cert_store.store import (  # noqa: F401 — re-export
    CertStore,  # S55 W1: re-export
)

__all__ = (
    "CertBackend",
    "CertEntry",
    "CertStore",
    "MemoryCertBackend",
    "MongoCertBackend",
    "PostgresCertBackend",
    "VaultCertBackend",
    "_fingerprint",
    "create_cert_store",
)


# --- Top-level re-exports (S55 W1 decomp: preserve original public surface) ---


def create_cert_store() -> CertStore:
    """Фабрика по умолчанию — собирает store из глобальных настроек."""
    return CertStore.from_settings(cert_store_settings)


# S171 M16: file watcher для cert hot-reload (D245)
from src.backend.infrastructure.security.cert_store.hot_reload import (  # noqa: F401 — re-export
    CertFileWatcher as CertFileWatcher,
)
