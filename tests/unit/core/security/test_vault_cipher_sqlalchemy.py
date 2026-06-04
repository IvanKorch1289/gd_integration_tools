"""Tests for vault_cipher_sqlalchemy helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.backend.core.security.vault_cipher_sqlalchemy import (
    decrypt_field,
    decrypt_mapping,
    encrypt_field,
    encrypt_mapping,
)


class FakeCipher:
    def __init__(self) -> None:
        self.encrypt = AsyncMock(return_value="vault:v1:abc123")
        self.decrypt = AsyncMock(return_value=b'{"x":1}')


class TestEncryptField:
    @pytest.mark.asyncio
    async def test_encrypts_value(self) -> None:
        cipher = FakeCipher()
        obj = type("O", (), {"data": {"key": "val"}})()
        await encrypt_field(obj, "data", cipher)
        cipher.encrypt.assert_awaited_once()
        assert obj.data == "vault:v1:abc123"

    @pytest.mark.asyncio
    async def test_skips_none(self) -> None:
        cipher = FakeCipher()
        obj = type("O", (), {"data": None})()
        await encrypt_field(obj, "data", cipher)
        cipher.encrypt.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_skips_already_encrypted(self) -> None:
        cipher = FakeCipher()
        obj = type("O", (), {"data": "vault:v1:old"})()
        await encrypt_field(obj, "data", cipher)
        cipher.encrypt.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_custom_serializer(self) -> None:
        cipher = FakeCipher()
        obj = type("O", (), {"data": 42})()
        await encrypt_field(obj, "data", cipher, serializer=lambda v: str(v))
        cipher.encrypt.assert_awaited_once_with("42")


class TestDecryptField:
    @pytest.mark.asyncio
    async def test_decrypts_value(self) -> None:
        cipher = FakeCipher()
        obj = type("O", (), {"data": "vault:v1:abc123"})()
        await decrypt_field(obj, "data", cipher)
        cipher.decrypt.assert_awaited_once_with("vault:v1:abc123")
        assert obj.data == {"x": 1}

    @pytest.mark.asyncio
    async def test_skips_none(self) -> None:
        cipher = FakeCipher()
        obj = type("O", (), {"data": None})()
        await decrypt_field(obj, "data", cipher)
        cipher.decrypt.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_skips_plaintext(self) -> None:
        cipher = FakeCipher()
        obj = type("O", (), {"data": "plain"})()
        await decrypt_field(obj, "data", cipher)
        cipher.decrypt.assert_not_awaited()
        assert obj.data == "plain"

    @pytest.mark.asyncio
    async def test_custom_deserializer(self) -> None:
        cipher = FakeCipher()
        cipher.decrypt = AsyncMock(return_value=b"hello")
        obj = type("O", (), {"data": "vault:v1:abc"})()
        await decrypt_field(
            obj, "data", cipher, deserializer=lambda v: v.decode().upper()
        )
        assert obj.data == "HELLO"


class TestEncryptMapping:
    @pytest.mark.asyncio
    async def test_encrypts_fields(self) -> None:
        cipher = FakeCipher()
        data = {"a": 1, "b": "plain"}
        result = await encrypt_mapping(data, ["a", "b"], cipher)
        assert result["a"] == "vault:v1:abc123"
        assert result["b"] == "vault:v1:abc123"

    @pytest.mark.asyncio
    async def test_skips_none_and_already_encrypted(self) -> None:
        cipher = FakeCipher()
        data = {"a": None, "b": "vault:v1:old"}
        result = await encrypt_mapping(data, ["a", "b"], cipher)
        cipher.encrypt.assert_not_awaited()
        assert result["a"] is None
        assert result["b"] == "vault:v1:old"

    @pytest.mark.asyncio
    async def test_does_not_mutate_original(self) -> None:
        cipher = FakeCipher()
        data = {"a": 1}
        result = await encrypt_mapping(data, ["a"], cipher)
        assert data["a"] == 1
        assert result["a"] == "vault:v1:abc123"


class TestDecryptMapping:
    @pytest.mark.asyncio
    async def test_decrypts_fields(self) -> None:
        cipher = FakeCipher()
        data = {"a": "vault:v1:abc"}
        result = await decrypt_mapping(data, ["a"], cipher)
        assert result["a"] == {"x": 1}

    @pytest.mark.asyncio
    async def test_skips_none_and_plaintext(self) -> None:
        cipher = FakeCipher()
        data = {"a": None, "b": "plain"}
        result = await decrypt_mapping(data, ["a", "b"], cipher)
        cipher.decrypt.assert_not_awaited()
        assert result["a"] is None
        assert result["b"] == "plain"
