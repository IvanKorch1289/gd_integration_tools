"""Unit-тесты :class:`RedisTokenRegistry` + :class:`EnvAESGCMKeyProvider`.

Sprint 25 W4 / ADR-NEW-21 / ADR-0068.

Покрывает:

* AES-256-GCM round-trip ``encrypt_value`` → ``decrypt_value``;
* graceful ``None`` при unavailable key version / invalid AES-GCM tag;
* TokenMap-serialize: ``store`` → Redis(orjson+base64+TTL) → ``retrieve``;
* "encryption at rest verified": raw Redis bytes ≠ plaintext (advisor recommendation);
* ``delete`` + ``cleanup_expired`` count;
* audit-emit вызывается для всех путей (success / failure / decrypt_failed);
* :class:`EnvAESGCMKeyProvider`: валидный base64 / invalid base64 / неверная длина / missing env.
"""

# ruff: noqa: S101  # assert — стандартная идиома pytest

from __future__ import annotations

import base64
import os
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.backend.core.security.pii_tokenizer import EncryptedValue, TokenMap
from src.backend.infrastructure.security.token_registry import (
    EnvAESGCMKeyProvider,
    RedisTokenRegistry,
    StaticAESGCMKeyProvider,
    TokenRegistryProtocol,
)

# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def aes_key() -> bytes:
    """Detrministic 32-byte AES-256-GCM ключ (для round-trip assert'ов)."""
    return bytes(range(32))


@pytest.fixture
def key_provider(aes_key: bytes) -> StaticAESGCMKeyProvider:
    return StaticAESGCMKeyProvider(keys={1: aes_key}, current_version=1)


@pytest.fixture
def audit_service() -> AsyncMock:
    """Mock unified AuditService с ``emit`` корутиной."""
    mock = AsyncMock()
    mock.emit = AsyncMock(return_value=None)
    return mock


@pytest.fixture
def fake_redis() -> Any:
    """Async Redis-совместимый клиент.

    Если ``fakeredis`` установлен — используется реальный fake с нативным
    ``scan_iter``. Иначе — простейшая реализация на ``dict``.
    """
    try:
        import fakeredis.aioredis as far  # noqa: PLC0415

        return far.FakeRedis()
    except ImportError:
        return _DictRedis()


class _DictRedis:
    """Минимальный async Redis-mock — ``get``/``set``/``delete``."""

    def __init__(self) -> None:
        self._data: dict[str, bytes] = {}
        self.set_calls: list[tuple[str, bytes, int | None]] = []
        self.del_calls: list[str] = []

    async def get(self, key: str) -> bytes | None:
        return self._data.get(key)

    async def set(
        self, key: str, value: bytes, *, ex: int | None = None, **_: Any
    ) -> bool:
        self._data[key] = value
        self.set_calls.append((key, value, ex))
        return True

    async def delete(self, key: str) -> int:
        self.del_calls.append(key)
        existed = key in self._data
        self._data.pop(key, None)
        return 1 if existed else 0


def _registry(
    *,
    redis_client: Any,
    key_provider: StaticAESGCMKeyProvider,
    audit_service: Any | None = None,
) -> RedisTokenRegistry:
    return RedisTokenRegistry(
        redis_client=redis_client,
        key_provider=key_provider,
        audit_service=audit_service,
    )


def _token_map(*, tokens: dict[str, EncryptedValue]) -> TokenMap:
    return TokenMap(
        tokens=tokens,
        policy_name="ru_strict_reversible",
        created_at=datetime.now(UTC),
        ttl_s=3600,
    )


# ── Crypto primitives ──────────────────────────────────────────────────────


def test_encrypt_decrypt_round_trip(
    fake_redis: Any, key_provider: StaticAESGCMKeyProvider
) -> None:
    """encrypt_value → decrypt_value возвращает исходный plaintext."""
    registry = _registry(redis_client=fake_redis, key_provider=key_provider)
    plaintext = "Иванов И.И., договор № 12345/CR-001"

    encrypted = registry.encrypt_value(plaintext)
    assert encrypted.key_version == 1
    assert len(encrypted.nonce) == 12
    assert len(encrypted.tag) == 16
    assert encrypted.ciphertext != plaintext.encode("utf-8")

    restored = registry.decrypt_value(encrypted)
    assert restored == plaintext


def test_decrypt_with_unavailable_key_version_returns_none(
    fake_redis: Any, key_provider: StaticAESGCMKeyProvider
) -> None:
    """decrypt_value(key_version=99) → None (rotation gap)."""
    registry = _registry(redis_client=fake_redis, key_provider=key_provider)
    encrypted = registry.encrypt_value("PII")
    # Подменяем версию на отсутствующую:
    rogue = EncryptedValue(
        ciphertext=encrypted.ciphertext,
        nonce=encrypted.nonce,
        tag=encrypted.tag,
        key_version=99,
    )
    assert registry.decrypt_value(rogue) is None


def test_decrypt_with_corrupted_tag_returns_none(
    fake_redis: Any, key_provider: StaticAESGCMKeyProvider
) -> None:
    """decrypt_value при invalid AES-GCM tag → None (не raise)."""
    registry = _registry(redis_client=fake_redis, key_provider=key_provider)
    encrypted = registry.encrypt_value("PII")
    tampered = EncryptedValue(
        ciphertext=encrypted.ciphertext,
        nonce=encrypted.nonce,
        tag=b"\x00" * 16,
        key_version=encrypted.key_version,
    )
    assert registry.decrypt_value(tampered) is None


def test_encrypt_raises_when_current_key_unavailable() -> None:
    """encrypt_value поднимает RuntimeError если key_provider пуст."""

    class _NullKeyProvider:
        current_version = 1

        def get_key(self, version: int) -> bytes | None:  # noqa: ARG002
            return None

    registry = RedisTokenRegistry(
        redis_client=_DictRedis(),
        key_provider=_NullKeyProvider(),  # type: ignore[arg-type]
    )
    with pytest.raises(RuntimeError, match="key version 1 unavailable"):
        registry.encrypt_value("PII")


# ── Storage API ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_store_retrieve_round_trip(
    fake_redis: Any, key_provider: StaticAESGCMKeyProvider
) -> None:
    """store(token_map) → retrieve(key) возвращает идентичный объект."""
    registry = _registry(redis_client=fake_redis, key_provider=key_provider)
    encrypted = registry.encrypt_value("Иванов И.И.")
    token_map = _token_map(tokens={"<PERSON_a8f3>": encrypted})

    await registry.store("corr-123", token_map, ttl_s=3600)

    restored = await registry.retrieve("corr-123")
    assert restored is not None
    assert restored.policy_name == "ru_strict_reversible"
    assert restored.ttl_s == 3600
    assert "<PERSON_a8f3>" in restored.tokens
    decrypted = registry.decrypt_value(restored.tokens["<PERSON_a8f3>"])
    assert decrypted == "Иванов И.И."


@pytest.mark.asyncio
async def test_retrieve_miss_returns_none(
    fake_redis: Any, key_provider: StaticAESGCMKeyProvider
) -> None:
    """retrieve(несуществующий ключ) → None."""
    registry = _registry(redis_client=fake_redis, key_provider=key_provider)
    assert await registry.retrieve("never-stored") is None


@pytest.mark.asyncio
async def test_retrieve_corrupted_json_returns_none(
    fake_redis: Any, key_provider: StaticAESGCMKeyProvider, audit_service: AsyncMock
) -> None:
    """Невалидный JSON в Redis → None + emit decrypt_failed."""
    registry = _registry(
        redis_client=fake_redis, key_provider=key_provider, audit_service=audit_service
    )
    await fake_redis.set("pii:token:bad", b"NOT-JSON{}}")
    result = await registry.retrieve("bad")
    assert result is None
    events = [c.kwargs["event"] for c in audit_service.emit.call_args_list]
    assert "ai.pii.tokenize.decrypt_failed" in events


@pytest.mark.asyncio
async def test_encryption_at_rest_raw_bytes_differ_from_plaintext(
    fake_redis: Any, key_provider: StaticAESGCMKeyProvider
) -> None:
    """Raw Redis-bytes не содержат plaintext (advisor recommendation)."""
    registry = _registry(redis_client=fake_redis, key_provider=key_provider)
    plaintext = "СОВЕРШЕННО_СЕКРЕТНОЕ_PII"
    encrypted = registry.encrypt_value(plaintext)
    token_map = _token_map(tokens={"<X_1>": encrypted})

    await registry.store("k1", token_map, ttl_s=60)

    raw = await fake_redis.get("pii:token:k1")
    assert raw is not None
    assert plaintext.encode("utf-8") not in raw
    # Сами зашифрованные bytes (ciphertext) в hex-base64 также не содержат plaintext:
    assert base64.b64encode(plaintext.encode("utf-8")) not in raw


@pytest.mark.asyncio
async def test_delete_removes_key(
    fake_redis: Any, key_provider: StaticAESGCMKeyProvider, audit_service: AsyncMock
) -> None:
    """delete(key) убирает запись из Redis и эмит audit."""
    registry = _registry(
        redis_client=fake_redis, key_provider=key_provider, audit_service=audit_service
    )
    encrypted = registry.encrypt_value("x")
    await registry.store("rm-me", _token_map(tokens={"<X_1>": encrypted}), ttl_s=60)
    assert await registry.retrieve("rm-me") is not None

    await registry.delete("rm-me")

    assert await registry.retrieve("rm-me") is None
    events = [c.kwargs["event"] for c in audit_service.emit.call_args_list]
    assert "ai.pii.tokenize.delete" in events


@pytest.mark.asyncio
async def test_cleanup_expired_counts_live_keys(
    fake_redis: Any, key_provider: StaticAESGCMKeyProvider
) -> None:
    """cleanup_expired возвращает число живых ключей под prefix."""
    registry = _registry(redis_client=fake_redis, key_provider=key_provider)
    encrypted = registry.encrypt_value("x")
    for i in range(3):
        await registry.store(
            f"key-{i}", _token_map(tokens={"<X_1>": encrypted}), ttl_s=60
        )

    count = await registry.cleanup_expired()
    assert count == 3


@pytest.mark.asyncio
async def test_store_emits_audit_with_token_count_and_key_version(
    fake_redis: Any, key_provider: StaticAESGCMKeyProvider, audit_service: AsyncMock
) -> None:
    """audit.emit для store содержит token_count + key_version."""
    registry = _registry(
        redis_client=fake_redis, key_provider=key_provider, audit_service=audit_service
    )
    encrypted = registry.encrypt_value("x")
    token_map = _token_map(tokens={"<X_1>": encrypted, "<X_2>": encrypted})

    await registry.store("ack", token_map, ttl_s=120)

    emit_calls = [c.kwargs for c in audit_service.emit.call_args_list]
    store_event = next(c for c in emit_calls if c["event"] == "ai.pii.tokenize.store")
    assert store_event["outcome"] == "success"
    assert store_event["details"]["token_count"] == 2
    assert store_event["details"]["key_version"] == 1
    assert store_event["details"]["ttl_s"] == 120


@pytest.mark.asyncio
async def test_ttl_pushed_to_redis_set_ex(
    key_provider: StaticAESGCMKeyProvider,
) -> None:
    """TTL пробрасывается в Redis.set(ex=ttl)."""
    client = _DictRedis()
    registry = _registry(redis_client=client, key_provider=key_provider)
    encrypted = registry.encrypt_value("x")

    await registry.store("k", _token_map(tokens={"<X_1>": encrypted}), ttl_s=42)

    assert client.set_calls
    _, _, ex = client.set_calls[-1]
    assert ex == 42


def test_registry_implements_protocol(
    fake_redis: Any, key_provider: StaticAESGCMKeyProvider
) -> None:
    """isinstance check на TokenRegistryProtocol (runtime_checkable)."""
    registry = _registry(redis_client=fake_redis, key_provider=key_provider)
    assert isinstance(registry, TokenRegistryProtocol)


# ── EnvAESGCMKeyProvider ───────────────────────────────────────────────────


def test_env_key_provider_valid_base64(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = bytes(range(32))
    monkeypatch.setenv("PII_AES_KEY_V1", base64.b64encode(raw).decode("ascii"))
    provider = EnvAESGCMKeyProvider(current_version=1)
    assert provider.get_key(1) == raw


def test_env_key_provider_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PII_AES_KEY_V1", raising=False)
    provider = EnvAESGCMKeyProvider(current_version=1)
    assert provider.get_key(1) is None


def test_env_key_provider_invalid_base64(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PII_AES_KEY_V1", "@@@not-base64@@@")
    provider = EnvAESGCMKeyProvider(current_version=1)
    assert provider.get_key(1) is None


def test_env_key_provider_wrong_length(monkeypatch: pytest.MonkeyPatch) -> None:
    """Decoded ≠ 32 bytes → None (AES-256-GCM требует ровно 32)."""
    monkeypatch.setenv("PII_AES_KEY_V1", base64.b64encode(b"too-short").decode("ascii"))
    provider = EnvAESGCMKeyProvider(current_version=1)
    assert provider.get_key(1) is None


def test_static_key_provider_rejects_wrong_length() -> None:
    with pytest.raises(ValueError, match="32 raw bytes"):
        StaticAESGCMKeyProvider(keys={1: b"short"}, current_version=1)


def test_static_key_provider_requires_at_least_one_key() -> None:
    with pytest.raises(ValueError, match="хотя бы один ключ"):
        StaticAESGCMKeyProvider(keys={}, current_version=1)


# Sanity ── избегаем побочного эффекта на тестовой среде после fixture'ов:
def _cleanup_env_pollution() -> None:
    for k in list(os.environ):
        if k.startswith("PII_AES_KEY_V"):
            del os.environ[k]
