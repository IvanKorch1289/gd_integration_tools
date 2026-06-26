"""TDD: EnvelopeEncryptionService (S171 M10 P1, D174).

Per-tenant DEK (Data Encryption Key) с envelope encryption.
Banking domain требует at-rest encryption.

Pattern:
- KEK (Key Encryption Key) — master key в Vault transit
- DEK (Data Encryption Key) — per-tenant, зашифрован KEK
- Data шифруется DEK
- DEK хранится зашифрованным вместе с ciphertext

Ponytail (D174): тонкий wrapper поверх cryptography library.
"""
# ruff: noqa: S101
from __future__ import annotations

import pytest


class TestEnvelopeEncryptionService:
    def test_instantiates(self) -> None:
        from src.backend.core.security.encryption.envelope import (
            EnvelopeEncryptionService,
        )
        svc = EnvelopeEncryptionService(
            kek_source="local", kek_id="test-key-1"
        )
        assert svc.kek_id == "test-key-1"
        assert svc.kek_source == "local"

    def test_supported_kek_sources(self) -> None:
        from src.backend.core.security.encryption.envelope import (
            EnvelopeEncryptionService,
        )
        assert "local" in EnvelopeEncryptionService.SUPPORTED_KEK_SOURCES
        assert "vault_transit" in EnvelopeEncryptionService.SUPPORTED_KEK_SOURCES

    def test_rejects_invalid_kek_source(self) -> None:
        from src.backend.core.security.encryption.envelope import (
            EnvelopeEncryptionService,
        )
        with pytest.raises(ValueError, match="kek_source"):
            EnvelopeEncryptionService(kek_source="invalid", kek_id="x")

    def test_generate_dek(self) -> None:
        from src.backend.core.security.encryption.envelope import (
            EnvelopeEncryptionService,
        )
        svc = EnvelopeEncryptionService(
            kek_source="local", kek_id="test-key-1"
        )
        # Generate plaintext DEK (256-bit AES key)
        dek = svc._generate_dek()
        assert isinstance(dek, bytes)
        assert len(dek) == 32  # 256 bits

    def test_encrypt_decrypt_roundtrip(self) -> None:
        from src.backend.core.security.encryption.envelope import (
            EnvelopeEncryptionService,
        )
        svc = EnvelopeEncryptionService(
            kek_source="local", kek_id="test-key-1"
        )
        plaintext = b"Hello, banking customer 12345"
        envelope = svc.encrypt(plaintext, tenant_id="tenant-1")
        assert "ciphertext" in envelope
        assert "encrypted_dek" in envelope
        assert "kek_id" in envelope
        assert "tenant_id" in envelope
        assert "algorithm" in envelope
        # Decrypt
        recovered = svc.decrypt(envelope)
        assert recovered == plaintext

    def test_different_tenants_get_different_deks(self) -> None:
        from src.backend.core.security.encryption.envelope import (
            EnvelopeEncryptionService,
        )
        svc = EnvelopeEncryptionService(
            kek_source="local", kek_id="test-key-1"
        )
        env1 = svc.encrypt(b"x", tenant_id="tenant-1")
        env2 = svc.encrypt(b"x", tenant_id="tenant-2")
        # Разные tenant → разные DEK → разные encrypted_dek
        assert env1["encrypted_dek"] != env2["encrypted_dek"]
        # Но оба decryptable
        assert svc.decrypt(env1) == b"x"
        assert svc.decrypt(env2) == b"x"

    def test_wrong_kek_cannot_decrypt(self) -> None:
        from src.backend.core.security.encryption.envelope import (
            EnvelopeEncryptionService,
        )
        svc1 = EnvelopeEncryptionService(
            kek_source="local", kek_id="key-A"
        )
        svc2 = EnvelopeEncryptionService(
            kek_source="local", kek_id="key-B"
        )
        envelope = svc1.encrypt(b"secret", tenant_id="t1")
        with pytest.raises(Exception, match="kek_id mismatch"):
            svc2.decrypt(envelope)
