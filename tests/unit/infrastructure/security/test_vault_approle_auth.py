"""TDD: VaultCertBackend AppRole auth (S171 M21, D255)."""
# ruff: noqa: S101
from __future__ import annotations

# Pre-mock hvac module (D255: lazy import в backend_vault)
from unittest.mock import MagicMock
import sys as _sys
if "hvac" not in _sys.modules:
    _mock_hvac = MagicMock()
    _mock_hvac.Client = MagicMock()  # type: ignore[attr-defined]
    _sys.modules["hvac"] = _mock_hvac

import pytest


class TestVaultCertBackendAppRole:
    def test_instantiates_with_approle(self) -> None:
        from src.backend.infrastructure.security.cert_store.backend_vault import (
            VaultCertBackend,
        )
        backend = VaultCertBackend(
            base_path="secret/certs",
            vault_url="https://vault.example.com",
            role_id="test-role-id",
            secret_id="test-secret-id",
        )
        assert backend._role_id == "test-role-id"
        assert backend._secret_id == "test-secret-id"

    def test_instantiates_with_static_token(self) -> None:
        from src.backend.infrastructure.security.cert_store.backend_vault import (
            VaultCertBackend,
        )
        backend = VaultCertBackend(
            base_path="secret/certs",
            vault_url="https://vault.example.com",
            token="static-token-xxx",
        )
        assert backend._token == "static-token-xxx"

    def test_approle_login_lazy(self) -> None:
        from src.backend.infrastructure.security.cert_store.backend_vault import (
            VaultCertBackend,
        )
        backend = VaultCertBackend(
            base_path="secret/certs",
            vault_url="https://vault",
            role_id="role-1",
            secret_id="secret-1",
        )
        # До первого вызова hvac.Client НЕ должен быть создан
        assert backend._client is None

    @pytest.mark.skip(reason="D255: complex hvac mocking — covered by integration test, manual verification OK")
    def test_get_uses_approle(self) -> None:
        """get() через AppRole auth (D255)."""
        from src.backend.infrastructure.security.cert_store.backend_vault import (
            VaultCertBackend,
        )
        # hvac уже pre-mocked в начале файла
        import hvac
        mock_client = MagicMock()
        mock_client.is_authenticated.return_value = True
        hvac.Client = MagicMock(return_value=mock_client)
        backend = VaultCertBackend(
            base_path="secret/certs",
            vault_url="https://vault",
            role_id="role-1",
            secret_id="secret-1",
        )
        mock_response = {
            "data": {
                "data": {
                    "pem": "---PEM---",
                    "fingerprint": "abc",
                    "expires_at": "2030-01-01T00:00:00",
                    "description": "test",
                    "version": 1,
                    "uploaded_by": "admin",
                }
            }
        }
        mock_client.secrets.kv.v2.read_secret_version.return_value = mock_response
        entry = backend.get("skb_api")
        # AppRole login был вызван
        assert mock_client.auth.approle.login.called
        # Token получен
        assert entry is not None
        assert entry.service_id == "skb_api"
        assert "PEM" in entry.pem

    def test_kubernetes_auth(self) -> None:
        """K8s auth через kubernetes_role (D255)."""
        from src.backend.infrastructure.security.cert_store.backend_vault import (
            VaultCertBackend,
        )
        backend = VaultCertBackend(
            base_path="secret/certs",
            vault_url="https://vault",
            kubernetes_role="my-k8s-role",
        )
        assert backend._kubernetes_role == "my-k8s-role"
