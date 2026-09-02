"""Unit-тесты ``infrastructure.security.cert_store`` — coverage ratchet (Post-Plan A Sprint 29).

core/infrastructure/security/cert_store subpackage (S55 W1 decomp from
628 LOC → 7 files per-class): re-exports ~9 symbols (CertStore facade +
MemoryCertBackend + PostgresCertBackend + VaultCertBackend +
MongoCertBackend + CertEntry + cert_store_settings + others).
~12 stmts, 0% coverage.

Цель slice: 0% → 100% через __all__ audit + class identity.
"""

from __future__ import annotations

import pytest

from src.backend.infrastructure.security import cert_store
from src.backend.infrastructure.security.cert_store import (
    CertBackend,
    CertEntry,
    CertStore,
    MemoryCertBackend,
    MongoCertBackend,
    PostgresCertBackend,
    VaultCertBackend,
    cert_store_settings,
)


@pytest.mark.unit
class TestCertStoreFacadeAllExports:
    """``__all__`` audit + class identity."""

    @pytest.mark.parametrize(
        "symbol_name",
        [
            "CertBackend",
            "CertEntry",
            "CertStore",
            "MemoryCertBackend",
            "MongoCertBackend",
            "PostgresCertBackend",
            "VaultCertBackend",
        ],
    )
    def test_all_exports_accessible(self, symbol_name: str) -> None:
        """Каждый символ из ``__all__`` доступен через facade."""
        assert hasattr(cert_store, symbol_name), (
            f"Missing export: {symbol_name}"
        )
        assert symbol_name in cert_store.__all__, (
            f"{symbol_name} not declared in __all__"
        )

    def test_all_declared_count(self) -> None:
        """``__all__`` содержит 9 символов (с CertBackend ABC base)."""
        assert len(cert_store.__all__) == 9

    def test_module_docstring_present(self) -> None:
        """Module docstring описывает S55 W1 decomp (7 classes в 7 files)."""
        assert cert_store.__doc__ is not None
        assert "S55 W1" in cert_store.__doc__ or "CertStore" in cert_store.__doc__


@pytest.mark.unit
class TestCertStoreFacadeIdentity:
    """Identity checks для 7 re-exports."""

    def test_cert_store_is_class(self) -> None:
        """``CertStore`` — class (main facade, 10 methods)."""
        assert isinstance(CertStore, type)

    def test_memory_cert_backend_is_class(self) -> None:
        """``MemoryCertBackend`` — class (in-memory backend)."""
        assert isinstance(MemoryCertBackend, type)

    def test_postgres_cert_backend_is_class(self) -> None:
        """``PostgresCertBackend`` — class (PostgreSQL backend)."""
        assert isinstance(PostgresCertBackend, type)

    def test_vault_cert_backend_is_class(self) -> None:
        """``VaultCertBackend`` — class (Vault PKI backend)."""
        assert isinstance(VaultCertBackend, type)

    def test_mongo_cert_backend_is_class(self) -> None:
        """``MongoCertBackend`` — class (MongoDB backend)."""
        assert isinstance(MongoCertBackend, type)

    def test_cert_entry_is_class(self) -> None:
        """``CertEntry`` — class (data model / Pydantic)."""
        assert isinstance(CertEntry, type)

    def test_cert_store_settings_is_instance(self) -> None:
        """``cert_store_settings`` — pre-initialized Pydantic settings instance."""
        # Pydantic Settings instance — has ``.model_dump()``
        assert hasattr(cert_store_settings, "model_dump")
