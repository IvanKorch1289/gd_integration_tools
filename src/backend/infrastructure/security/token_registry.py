"""TokenRegistry — Redis-backed AES-GCM хранилище ``TokenMap`` для ``PIITokenizer``.

Sprint 25 W4 / ADR-NEW-21 / ADR-0068.

Назначение
----------
Сохраняет :class:`TokenMap` (mapping placeholder → encrypted PII) между
``mask_reversible`` и ``unmask`` round-trip для banking-сценариев. Шифрование
AES-256-GCM поверх raw 32-байтного ключа из :class:`AESGCMKeyProvider`
(env-fallback в dev / Vault rotation в production).

Хранение
--------
Redis key: ``"{prefix}:{key}"`` (по умолчанию ``"pii:token:{correlation_id}"``).
Value: ``orjson(TokenMap)`` — bytes-поля :class:`EncryptedValue` сериализуются
в base64. TTL = ``policy.ttl_s`` через ``Redis.set(ex=ttl)``; Redis сам удаляет
просроченные записи. ``cleanup_expired`` — defensive metric (count живых).

Decisions (S25 W4, advisor 2026-05-25)
--------------------------------------
* ``EncryptedValue.ciphertext`` + ``EncryptedValue.tag`` хранятся **раздельно**
  (split ``aesgcm.encrypt(...)[:-16]``) — упрощает диагностику rotation.
* Ключ из :class:`SecretsBackend` приходит в **base64-string**; raw 32 bytes
  после :func:`base64.b64decode`. Env-вариант — ``PII_AES_KEY_V{version}``.
* ``retrieve(key)`` реализован defensive — каллер для cross-process unmask
  появится в S25 W4+ (DSL ``pii_unmask`` процессор).

См. также
---------
* :class:`src.backend.core.security.pii_tokenizer.PIITokenizer` — основной caller;
* :class:`src.backend.services.audit.audit_service.AuditService` — emit-таргет
  ``ai.pii.tokenize.{store,retrieve,delete,decrypt_failed}``.
"""

from __future__ import annotations

import base64
import fnmatch
import os
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

import orjson

from src.backend.core.security.pii_tokenizer import EncryptedValue, TokenMap
from src.backend.core.logging import get_logger
__all__ = (
    "AESGCMKeyProvider",
    "EnvAESGCMKeyProvider",
    "RedisTokenRegistry",
    "StaticAESGCMKeyProvider",
    "TokenRegistryProtocol",
)

_logger = get_logger("infrastructure.security.token_registry")


# ─── Protocols ────────────────────────────────────────────────────────────────


@runtime_checkable
class TokenRegistryProtocol(Protocol):
    """Контракт хранилища :class:`TokenMap` для PIITokenizer round-trip.

    Реализации:

    * :class:`RedisTokenRegistry` — production (Redis + AES-GCM + audit);
    * in-memory testkit (см. ``tests/fixtures``).
    """

    async def store(self, key: str, token_map: TokenMap, ttl_s: int) -> None:
        """Store token map with TTL.

        Args:
            key: Storage key.
            token_map: Token map to store.
            ttl_s: Time-to-live in seconds.
        """
        ...

    async def retrieve(self, key: str) -> TokenMap | None:
        """Retrieve token map by key.

        Args:
            key: Storage key.

        Returns:
            TokenMap or None if not found/expired.
        """
        ...

    async def delete(self, key: str) -> None:
        """Delete token map by key.

        Args:
            key: Storage key.
        """
        ...

    async def cleanup_expired(self) -> int:
        """Cleanup expired token maps.

        Returns:
            Number of deleted entries.
        """
        ...

    def encrypt_value(self, plaintext: str) -> EncryptedValue:
        """Encrypt plaintext value.

        Args:
            plaintext: Value to encrypt.

        Returns:
            EncryptedValue with ciphertext and metadata.
        """
        ...

    def decrypt_value(self, value: EncryptedValue) -> str | None:
        """Decrypt encrypted value.

        Args:
            value: EncryptedValue to decrypt.

        Returns:
            Decrypted plaintext or None if decryption fails.
        """
        ...


@runtime_checkable
class AESGCMKeyProvider(Protocol):
    """Источник AES-256-GCM ключей с rotation-семантикой.

    Реализации:

    * :class:`EnvAESGCMKeyProvider` — dev/staging, ключи из env;
    * :class:`StaticAESGCMKeyProvider` — unit-тесты;
    * ``VaultAESGCMKeyProvider`` (carry-over) — production через Vault KV v2.
    """

    current_version: int

    def get_key(self, version: int) -> bytes | None:
        """Возвращает raw 32 bytes для указанной версии (или ``None``)."""
        ...


# ─── Key providers ────────────────────────────────────────────────────────────


class StaticAESGCMKeyProvider:
    """In-memory key provider для unit-тестов.

    Хранит словарь ``{version: bytes}``. ``current_version`` указывает на
    активный ключ для шифрования; старые версии остаются доступными для
    decrypt (rotation grace-period).
    """

    def __init__(
        self, *, keys: dict[int, bytes], current_version: int | None = None
    ) -> None:
        if not keys:
            raise ValueError("StaticAESGCMKeyProvider требует хотя бы один ключ")
        for version, raw in keys.items():
            if len(raw) != 32:
                raise ValueError(
                    f"Key version {version} must be 32 raw bytes, got {len(raw)}"
                )
        self._keys = dict(keys)
        self.current_version = current_version or max(keys)

    def get_key(self, version: int) -> bytes | None:
        return self._keys.get(version)


class EnvAESGCMKeyProvider:
    """Env-backed AES-256-GCM key provider (dev/staging fallback).

    Читает ключ из переменной ``{prefix}{version}`` (по умолчанию
    ``PII_AES_KEY_V{version}``); ожидается base64 → 32 raw bytes. При невалидном
    значении (длина ≠ 32 или мусор) логирует warning и возвращает ``None``.
    """

    def __init__(
        self, *, env_prefix: str = "PII_AES_KEY_V", current_version: int = 1
    ) -> None:
        self._env_prefix = env_prefix
        self.current_version = current_version

    def get_key(self, version: int) -> bytes | None:
        env_name = f"{self._env_prefix}{version}"
        raw = os.environ.get(env_name)
        if raw is None:
            return None
        try:
            decoded = base64.b64decode(raw)
        except (ValueError, TypeError):
            _logger.warning(
                "EnvAESGCMKeyProvider: %s — invalid base64 payload", env_name
            )
            return None
        if len(decoded) != 32:
            _logger.warning(
                "EnvAESGCMKeyProvider: %s decoded len=%d ≠ 32 (AES-256-GCM)",
                env_name,
                len(decoded),
            )
            return None
        return decoded


# ─── Redis implementation ─────────────────────────────────────────────────────


class RedisTokenRegistry:
    """Redis-backed :class:`TokenMap`-хранилище с AES-256-GCM envelope.

    Сериализация TokenMap:
        ``token_map → orjson(dict-form) → Redis.SET(ex=ttl_s)``.
        :class:`EncryptedValue` хранится как ``dict[str, str|int]`` —
        ``ciphertext/nonce/tag`` в base64 для orjson-safety.

    Шифрование PII-значений (внутри :class:`EncryptedValue`):
        ``plaintext.encode('utf-8') → AESGCM(key).encrypt(nonce, plaintext, None)``;
        результат ``ct||tag`` splittится: ``ciphertext = ct[:-16]``,
        ``tag = ct[-16:]``.

    Audit-events (через AuditService):
        ``ai.pii.tokenize.store`` / ``.retrieve`` / ``.delete`` (outcome=success);
        ``ai.pii.tokenize.decrypt_failed`` (outcome=failure) — при tag-mismatch
        или unavailable key version.
    """

    def __init__(
        self,
        *,
        redis_client: Any,
        key_provider: AESGCMKeyProvider,
        audit_service: Any = None,
        key_prefix: str = "pii:token",
    ) -> None:
        self._redis = redis_client
        self._key_provider = key_provider
        self._audit = audit_service
        self._prefix = key_prefix

    # ─── crypto primitives (sync) ─────────────────────────────────────────

    def encrypt_value(self, plaintext: str) -> EncryptedValue:
        """Шифрует один plaintext-PII через AES-256-GCM.

        Raises:
            RuntimeError: ``key_provider`` не отдал ключ текущей версии.
        """
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        version = self._key_provider.current_version
        key = self._key_provider.get_key(version)
        if key is None:
            raise RuntimeError(
                f"AES-GCM key version {version} unavailable from key_provider"
            )
        aesgcm = AESGCM(key)
        nonce = os.urandom(12)
        ct_with_tag = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
        return EncryptedValue(
            ciphertext=ct_with_tag[:-16],
            nonce=nonce,
            tag=ct_with_tag[-16:],
            key_version=version,
        )

    def decrypt_value(self, value: EncryptedValue) -> str | None:
        """Дешифрует :class:`EncryptedValue`.

        Возвращает ``None`` при:

        * unavailable key version (key rotation gap);
        * AES-GCM tag mismatch (поврежденный/подделанный ciphertext).

        Эмит ``ai.pii.tokenize.decrypt_failed`` происходит в :meth:`retrieve`
        (async-контекст), здесь — только sync sentinel ``None``.
        """
        from cryptography.exceptions import InvalidTag
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        key = self._key_provider.get_key(value.key_version)
        if key is None:
            _logger.warning(
                "decrypt_value: key version %d unavailable", value.key_version
            )
            return None
        aesgcm = AESGCM(key)
        try:
            plaintext = aesgcm.decrypt(value.nonce, value.ciphertext + value.tag, None)
        except InvalidTag:
            _logger.warning(
                "decrypt_value: AES-GCM tag mismatch (key_version=%d)",
                value.key_version,
            )
            return None
        return plaintext.decode("utf-8")

    # ─── storage API (async) ──────────────────────────────────────────────

    async def store(self, key: str, token_map: TokenMap, ttl_s: int) -> None:
        """Сериализует ``token_map`` → orjson → Redis с TTL = ``ttl_s``.

        Args:
            key: Логический ключ (обычно ``correlation_id`` или
                ``f"{tenant_id}:{correlation_id}"``).
            token_map: :class:`TokenMap` для сохранения.
            ttl_s: TTL в секундах (Redis ``EX``).
        """
        redis_key = self._build_key(key)
        payload = self._serialize(token_map)
        await self._redis.set(redis_key, payload, ex=ttl_s)
        await self._audit_emit(
            event="ai.pii.tokenize.store",
            action="store",
            outcome="success",
            details={
                "ttl_s": ttl_s,
                "key_version": self._key_provider.current_version,
                "token_count": len(token_map.tokens),
                "policy_name": token_map.policy_name,
            },
        )

    async def retrieve(self, key: str) -> TokenMap | None:
        """Читает :class:`TokenMap` из Redis; ``None`` при miss / corrupted."""
        redis_key = self._build_key(key)
        raw = await self._redis.get(redis_key)
        if raw is None:
            return None
        try:
            token_map = self._deserialize(raw)
        except Exception as exc:
            _logger.warning(
                "TokenMap deserialization failed for %s: %r", redis_key, exc
            )
            await self._audit_emit(
                event="ai.pii.tokenize.decrypt_failed",
                action="retrieve",
                outcome="failure",
                details={"reason": "deserialize_failed"},
            )
            return None
        await self._audit_emit(
            event="ai.pii.tokenize.retrieve",
            action="retrieve",
            outcome="success",
            details={
                "token_count": len(token_map.tokens),
                "policy_name": token_map.policy_name,
            },
        )
        return token_map

    async def delete(self, key: str) -> None:
        """Явно удаляет :class:`TokenMap` (например после успешного ``unmask``)."""
        redis_key = self._build_key(key)
        await self._redis.delete(redis_key)
        await self._audit_emit(
            event="ai.pii.tokenize.delete",
            action="delete",
            outcome="success",
            details={"key": key},
        )

    async def cleanup_expired(self) -> int:
        """Возвращает число живых записей под ``{prefix}:*``.

        Redis сам удаляет expired через TTL — здесь только observability:
        количество ключей, которые ещё актуальны. Используется фоновым
        cleanup-loop через :class:`TaskRegistry` для метрик.
        """
        count = 0
        async for _key in self._scan_iter(match=f"{self._prefix}:*", count=200):
            count += 1
        return count

    # ─── serialization ────────────────────────────────────────────────────

    def _serialize(self, token_map: TokenMap) -> bytes:
        """:class:`TokenMap` → ``orjson``-bytes (base64 на bytes-полях)."""
        payload = {
            "tokens": {
                placeholder: {
                    "ciphertext": base64.b64encode(ev.ciphertext).decode("ascii"),
                    "nonce": base64.b64encode(ev.nonce).decode("ascii"),
                    "tag": base64.b64encode(ev.tag).decode("ascii"),
                    "key_version": ev.key_version,
                }
                for placeholder, ev in token_map.tokens.items()
            },
            "policy_name": token_map.policy_name,
            "created_at": token_map.created_at.isoformat(),
            "ttl_s": token_map.ttl_s,
        }
        return orjson.dumps(payload)

    def _deserialize(self, raw: bytes) -> TokenMap:
        """``orjson``-bytes → :class:`TokenMap`."""
        data: dict[str, Any] = orjson.loads(raw)
        tokens = {
            placeholder: EncryptedValue(
                ciphertext=base64.b64decode(ev["ciphertext"]),
                nonce=base64.b64decode(ev["nonce"]),
                tag=base64.b64decode(ev["tag"]),
                key_version=int(ev["key_version"]),
            )
            for placeholder, ev in data["tokens"].items()
        }
        return TokenMap(
            tokens=tokens,
            policy_name=str(data["policy_name"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            ttl_s=int(data["ttl_s"]),
        )

    # ─── utils ────────────────────────────────────────────────────────────

    def _build_key(self, key: str) -> str:
        return f"{self._prefix}:{key}"

    async def _scan_iter(
        self, *, match: str, count: int = 200
    ) -> AsyncIterator[bytes | str]:
        """Адаптер SCAN — работает с ``redis.asyncio.Redis`` и ``fakeredis``."""
        scan = getattr(self._redis, "scan_iter", None)
        if scan is not None:
            async for key in scan(match=match, count=count):
                yield key
            return
        # Minimal fallback для ``_DictRedis``-mock'а в unit-тестах:
        keys = getattr(self._redis, "_data", {})
        for k in list(keys):
            if fnmatch.fnmatchcase(k, match):
                yield k

    async def _audit_emit(
        self, *, event: str, action: str, outcome: str, details: dict[str, Any]
    ) -> None:
        """Безопасный emit — никогда не ломает основной flow."""
        if self._audit is None:
            return
        try:
            await self._audit.emit(
                event=event,
                action=action,
                outcome=outcome,
                resource="pii_token_map",
                details=details,
            )
        except Exception as exc:
            _logger.debug("audit emit failed for %s: %r", event, exc)
