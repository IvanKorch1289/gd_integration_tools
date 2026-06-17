"""Tests for src.backend.core.config.vault."""

from __future__ import annotations

from src.backend.core.config.vault import VaultSettings


class TestVaultSettings:
    def test_defaults(self) -> None:
        s = VaultSettings()
        # S162 W6: Sibling Sprint 7 + conftest set VAULT_ENABLED=false
        # for test isolation. Production default is True, but in tests
        # it's False (per conftest env override).
        assert s.enabled is False
        assert s.addr == "http://127.0.0.1:8200"
        assert s.secret_path == "app/config"

    def test_coerce_empty_string(self) -> None:
        s = VaultSettings(enabled="")
        assert s.enabled is True

    def test_coerce_false(self) -> None:
        s = VaultSettings(enabled="false")
        assert s.enabled is False
        s2 = VaultSettings(enabled="0")
        assert s2.enabled is False

    def test_coerce_true(self) -> None:
        s = VaultSettings(enabled="true")
        assert s.enabled is True
        s2 = VaultSettings(enabled="1")
        assert s2.enabled is True
