"""Tests for src.backend.core.config.cert_store."""

from __future__ import annotations

import pytest

from src.backend.core.config.cert_store import CertStoreSettings


class TestCertStoreSettings:
    def test_defaults(self) -> None:
        s = CertStoreSettings()
        assert s.backend == "postgres"
        assert s.hot_cache_ttl == 300
        assert s.vault_path == "secret/certs"
        assert s.mongo_collection == "certs"
        assert s.expire_warn_days == 30

    def test_custom_values(self) -> None:
        s = CertStoreSettings(backend="vault", hot_cache_ttl=60, expire_warn_days=14)
        assert s.backend == "vault"
        assert s.hot_cache_ttl == 60
        assert s.expire_warn_days == 14

    def test_validation_bounds(self) -> None:
        with pytest.raises(Exception):
            CertStoreSettings(hot_cache_ttl=-1)
        with pytest.raises(Exception):
            CertStoreSettings(expire_warn_days=0)
