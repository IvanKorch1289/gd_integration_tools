"""Unit tests for src.backend.core.security.vault_cipher."""

from __future__ import annotations

import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.core.security.vault_cipher import VaultCipherError, VaultTransitCipher


@pytest.fixture(autouse=True)
def _reset_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VAULT_ADDR", raising=False)
    monkeypatch.delenv("VAULT_TOKEN", raising=False)


class TestVaultTransitCipherInit:
    def test_defaults(self) -> None:
        cipher = VaultTransitCipher(key_name="test-key")
        assert cipher.key_name == "test-key"
        assert cipher.mount_path == "transit"
        assert cipher.vault_addr == "http://localhost:8200"
        assert cipher.vault_token == ""
        assert cipher.timeout == 2.0
        assert cipher._max_connections == 32
        assert cipher._max_keepalive == 16
        assert cipher._client is None

    def test_custom_params(self) -> None:
        cipher = VaultTransitCipher(
            key_name="k",
            mount_path="/custom/",
            vault_addr="https://vault:8200/",
            vault_token="tk",
            timeout=5.0,
            max_connections=64,
            max_keepalive_connections=8,
        )
        assert cipher.key_name == "k"
        assert cipher.mount_path == "custom"
        assert cipher.vault_addr == "https://vault:8200"
        assert cipher.vault_token == "tk"
        assert cipher.timeout == 5.0
        assert cipher._max_connections == 64
        assert cipher._max_keepalive == 8

    def test_env_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VAULT_ADDR", "http://env-vault:8200")
        monkeypatch.setenv("VAULT_TOKEN", "env-token")
        cipher = VaultTransitCipher(key_name="k")
        assert cipher.vault_addr == "http://env-vault:8200"
        assert cipher.vault_token == "env-token"

    def test_no_token_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level("WARNING", logger="security.vault_cipher"):
            VaultTransitCipher(key_name="k")
        assert "без VAULT_TOKEN" in caplog.text


class TestEnsureClient:
    def test_lazy_init(self) -> None:
        cipher = VaultTransitCipher(key_name="k", vault_token="t")
        mock_client = MagicMock()
        with patch(
            "src.backend.core.net.migration_helper.make_http_client",
            return_value=mock_client,
        ) as mock_make:
            client = cipher._ensure_client()
        assert client is mock_client
        mock_make.assert_called_once()
        call_kwargs = mock_make.call_args.kwargs
        assert call_kwargs["plugin"] == "core.security.vault_cipher"
        assert call_kwargs["base_url"] == cipher.vault_addr
        assert call_kwargs["http2"] is True
        assert call_kwargs["timeout"] == cipher.timeout
        assert call_kwargs["headers"] == {"X-Vault-Token": "t"}

    def test_lazy_init_no_token(self) -> None:
        cipher = VaultTransitCipher(key_name="k")
        mock_client = MagicMock()
        with patch(
            "src.backend.core.net.migration_helper.make_http_client",
            return_value=mock_client,
        ) as mock_make:
            client = cipher._ensure_client()
        assert client is mock_client
        assert mock_make.call_args.kwargs["headers"] == {}

    def test_singleton_reuse(self) -> None:
        cipher = VaultTransitCipher(key_name="k", vault_token="t")
        mock_client = MagicMock()
        with patch(
            "src.backend.core.net.migration_helper.make_http_client",
            return_value=mock_client,
        ):
            c1 = cipher._ensure_client()
            c2 = cipher._ensure_client()
        assert c1 is c2 is mock_client


@pytest.mark.asyncio
class TestEncrypt:
    async def test_success_bytes(self) -> None:
        cipher = VaultTransitCipher(key_name="k", vault_token="t")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": {"ciphertext": "vault:v1:abc"}}
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        cipher._client = mock_client

        result = await cipher.encrypt(b"hello")
        assert result == "vault:v1:abc"
        mock_client.post.assert_awaited_once_with(
            "/v1/transit/encrypt/k",
            json={"plaintext": base64.b64encode(b"hello").decode("ascii")},
        )

    async def test_success_str(self) -> None:
        cipher = VaultTransitCipher(key_name="k", vault_token="t")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": {"ciphertext": "vault:v1:abc"}}
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        cipher._client = mock_client

        result = await cipher.encrypt("привет")
        assert result == "vault:v1:abc"
        expected_b64 = base64.b64encode("привет".encode("utf-8")).decode("ascii")
        mock_client.post.assert_awaited_once_with(
            "/v1/transit/encrypt/k", json={"plaintext": expected_b64}
        )

    async def test_network_error(self) -> None:
        cipher = VaultTransitCipher(key_name="k", vault_token="t")
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=ConnectionError("boom"))
        cipher._client = mock_client
        with pytest.raises(VaultCipherError, match="encrypt network error"):
            await cipher.encrypt(b"x")

    async def test_http_error(self) -> None:
        cipher = VaultTransitCipher(key_name="k", vault_token="t")
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.text = "permission denied"
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        cipher._client = mock_client
        with pytest.raises(VaultCipherError, match="encrypt HTTP 403"):
            await cipher.encrypt(b"x")

    async def test_bad_response_missing_key(self) -> None:
        cipher = VaultTransitCipher(key_name="k", vault_token="t")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": {}}
        mock_resp.text = "{}"
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        cipher._client = mock_client
        with pytest.raises(VaultCipherError, match="encrypt bad response"):
            await cipher.encrypt(b"x")

    async def test_invalid_ciphertext_format(self) -> None:
        cipher = VaultTransitCipher(key_name="k", vault_token="t")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": {"ciphertext": "not-vault"}}
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        cipher._client = mock_client
        with pytest.raises(VaultCipherError, match="invalid ciphertext"):
            await cipher.encrypt(b"x")


@pytest.mark.asyncio
class TestDecrypt:
    async def test_success(self) -> None:
        cipher = VaultTransitCipher(key_name="k", vault_token="t")
        b64_pt = base64.b64encode(b"secret").decode("ascii")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": {"plaintext": b64_pt}}
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        cipher._client = mock_client

        result = await cipher.decrypt("vault:v1:abc")
        assert result == b"secret"
        mock_client.post.assert_awaited_once_with(
            "/v1/transit/decrypt/k", json={"ciphertext": "vault:v1:abc"}
        )

    async def test_invalid_format_not_str(self) -> None:
        cipher = VaultTransitCipher(key_name="k", vault_token="t")
        with pytest.raises(VaultCipherError, match="invalid ciphertext format"):
            await cipher.decrypt(123)

    async def test_invalid_format_no_prefix(self) -> None:
        cipher = VaultTransitCipher(key_name="k", vault_token="t")
        with pytest.raises(VaultCipherError, match="invalid ciphertext format"):
            await cipher.decrypt("plain-text")

    async def test_network_error(self) -> None:
        cipher = VaultTransitCipher(key_name="k", vault_token="t")
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=TimeoutError("timeout"))
        cipher._client = mock_client
        with pytest.raises(VaultCipherError, match="decrypt network error"):
            await cipher.decrypt("vault:v1:x")

    async def test_http_error(self) -> None:
        cipher = VaultTransitCipher(key_name="k", vault_token="t")
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "internal error"
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        cipher._client = mock_client
        with pytest.raises(VaultCipherError, match="decrypt HTTP 500"):
            await cipher.decrypt("vault:v1:x")

    async def test_bad_response(self) -> None:
        cipher = VaultTransitCipher(key_name="k", vault_token="t")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": {}}
        mock_resp.text = "{}"
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        cipher._client = mock_client
        with pytest.raises(VaultCipherError, match="decrypt bad response"):
            await cipher.decrypt("vault:v1:x")

    async def test_base64_error(self) -> None:
        cipher = VaultTransitCipher(key_name="k", vault_token="t")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": {"plaintext": "A"}}
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        cipher._client = mock_client
        with pytest.raises(VaultCipherError, match="base64 error"):
            await cipher.decrypt("vault:v1:x")


@pytest.mark.asyncio
class TestRotate:
    async def test_success(self, caplog: pytest.LogCaptureFixture) -> None:
        cipher = VaultTransitCipher(key_name="k", vault_token="t")
        rotate_resp = MagicMock()
        rotate_resp.status_code = 204
        rotate_resp.text = ""
        meta_resp = MagicMock()
        meta_resp.status_code = 200
        meta_resp.json.return_value = {"data": {"latest_version": 7}}

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=rotate_resp)
        mock_client.get = AsyncMock(return_value=meta_resp)
        cipher._client = mock_client

        with caplog.at_level("INFO", logger="security.vault_cipher"):
            version = await cipher.rotate()
        assert version == 7
        assert "rotated" in caplog.text
        mock_client.post.assert_awaited_once_with("/v1/transit/keys/k/rotate", json={})
        mock_client.get.assert_awaited_once_with("/v1/transit/keys/k")

    async def test_network_error_on_rotate(self) -> None:
        cipher = VaultTransitCipher(key_name="k", vault_token="t")
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=OSError("net"))
        cipher._client = mock_client
        with pytest.raises(VaultCipherError, match="rotate network error"):
            await cipher.rotate()

    async def test_http_error_on_rotate(self) -> None:
        cipher = VaultTransitCipher(key_name="k", vault_token="t")
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.text = "forbidden"
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        cipher._client = mock_client
        with pytest.raises(VaultCipherError, match="rotate HTTP 403"):
            await cipher.rotate()

    async def test_network_error_on_read_key(self) -> None:
        cipher = VaultTransitCipher(key_name="k", vault_token="t")
        rotate_resp = MagicMock()
        rotate_resp.status_code = 200
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=rotate_resp)
        mock_client.get = AsyncMock(side_effect=OSError("net"))
        cipher._client = mock_client
        with pytest.raises(VaultCipherError, match="read-key network error"):
            await cipher.rotate()

    async def test_http_error_on_read_key(self) -> None:
        cipher = VaultTransitCipher(key_name="k", vault_token="t")
        rotate_resp = MagicMock()
        rotate_resp.status_code = 200
        read_resp = MagicMock()
        read_resp.status_code = 404
        read_resp.text = "not found"
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=rotate_resp)
        mock_client.get = AsyncMock(return_value=read_resp)
        cipher._client = mock_client
        with pytest.raises(VaultCipherError, match="read-key HTTP 404"):
            await cipher.rotate()

    async def test_bad_version_response(self) -> None:
        cipher = VaultTransitCipher(key_name="k", vault_token="t")
        rotate_resp = MagicMock()
        rotate_resp.status_code = 200
        read_resp = MagicMock()
        read_resp.status_code = 200
        read_resp.json.return_value = {"data": {"latest_version": "seven"}}
        read_resp.text = "bad"
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=rotate_resp)
        mock_client.get = AsyncMock(return_value=read_resp)
        cipher._client = mock_client
        with pytest.raises(VaultCipherError, match="read-key bad response"):
            await cipher.rotate()


@pytest.mark.asyncio
class TestClose:
    async def test_close(self) -> None:
        cipher = VaultTransitCipher(key_name="k", vault_token="t")
        mock_client = AsyncMock()
        cipher._client = mock_client
        await cipher.close()
        mock_client.aclose.assert_awaited_once()
        assert cipher._client is None

    async def test_close_idempotent(self) -> None:
        cipher = VaultTransitCipher(key_name="k", vault_token="t")
        await cipher.close()
        assert cipher._client is None
