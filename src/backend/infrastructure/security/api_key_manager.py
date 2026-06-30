"""Менеджер API-ключей с поддержкой ротации.

Хранит ключи в Redis с версионированием и grace period.
Поддерживает per-client ключи и аудит ротации.

Ключ валиден если:
1. Совпадает с текущим активным ключом клиента, ИЛИ
2. Совпадает с предыдущим ключом в grace period, ИЛИ
3. Совпадает с глобальным ключом из настроек (fallback).

S172 M2 (ARC-004): новые ключи хранятся через :class:`APIKeyAuth`
(Argon2id PHC). Старые SHA-256 хеши продолжают верифицироваться через
:meth:`APIKeyAuth.verify` (dual-verify path) для backward-compat.
Миграция SHA → Argon2 для существующих ключей — через
``tools/migrations/migrate_api_keys_to_argon2.py``.
"""

import secrets
import time
from dataclasses import dataclass
from typing import Any

from src.backend.core.auth.api_key_backend import APIKeyAuth, is_argon2_hash
from src.backend.core.logging import get_logger

__all__ = ("APIKeyInfo", "APIKeyManager", "get_api_key_manager")

logger = get_logger("security.api_keys")

_KEY_PREFIX = "apikey:"
_AUDIT_PREFIX = "apikey_audit:"


@dataclass(slots=True)
class APIKeyInfo:
    """Информация об API-ключе."""

    client_id: str
    key_hash: str
    version: int = 1
    created_at: float = 0.0
    expires_at: float | None = None
    is_active: bool = True
    description: str = ""


class APIKeyManager:
    """Менеджер ротации API-ключей.

    Хранит ключи в Redis (хешированные Argon2id — S172 M2).
    Backward-compat: legacy SHA-256 hashes принимаются через
    :class:`APIKeyAuth.verify` (grace period ~2 спринта).
    Grace period: старый ключ валиден N секунд после ротации.
    """

    def __init__(self, grace_period_seconds: int = 86400) -> None:
        self._grace_period = grace_period_seconds
        self._global_key_hash: str | None = None
        self._hasher = APIKeyAuth()  # OWASP-2026 baseline parameters

    async def _emit_audit_event(
        self,
        event_type: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Emit audit-event в Redis-stream ``apikey_audit:events``.

        Используется для non-success paths (verify errors, migration events)
        — distributed tracing видит эти события через Stream consumer.

        Args:
            event_type: Schema-free string id (``auth.global_verify_error``).
            payload: Optional dict. ``client_id`` / ``actor`` / ``timestamp``
                кладутся через ``add_to_stream``.
        """
        try:
            from src.backend.infrastructure.clients.storage.redis import (
                get_redis_client as redis_client,
            )

            data: dict[str, str] = {
                "event": event_type,
                "timestamp": str(time.time()),
            }
            if payload:
                for k, v in payload.items():
                    data[k] = str(v) if v is not None else ""
            await redis_client().add_to_stream(  # type: ignore[attr-defined]
                stream_name=_AUDIT_PREFIX + "events",
                data=data,
            )
        except Exception as exc:  # never fail caller
            logger.debug(
                "Audit-event emit failed (event=%s): %s", event_type, exc
            )

    def _init_global_key(self) -> None:
        """Кэширует хеш глобального ключа из настроек."""
        if self._global_key_hash is None:
            from src.backend.core.config.settings import settings

            self._global_key_hash = self._hasher.hash_key(settings.secure.api_key)

    def _hash_key(self, key: str) -> str:
        """Хеширует через :class:`APIKeyAuth` (Argon2id primary)."""
        return self._hasher.hash_key(key)

    def _verify_against_hash(self, raw_key: str, stored_hash: str) -> bool:
        """Verify raw_key против stored hash через :class:`APIKeyAuth`.

        Поддерживает оба формата: Argon2 PHC (primary) и SHA-256 hex
        (legacy compat). Constant-time по design.
        """
        return self._hasher.verify(raw_key, stored_hash)

    async def validate_key(self, raw_key: str) -> APIKeyInfo | None:
        """Проверяет API-ключ.

        Returns:
            APIKeyInfo если ключ валиден, None если нет.

        Notes:
            Pre-S172: SHA-256 hash сравнивается с stored SHA.
            S172 M2: stored hash — Argon2 PHC (новый) или SHA-256 hex
            (legacy). Verify делегирует :class:`APIKeyAuth.verify`.
        """
        self._init_global_key()

        # 1. Проверка глобального ключа (fallback).
        #    Argon2 verify — non-trivial CPU cost (~50ms на 64MB);
        #    если stored hash — Argon2, делаем один verify.
        #    M2.3 review S-3 fix: error path emits audit-event (Redis-stream),
        #    не silent swallow.
        if self._global_key_hash:
            try:
                if self._verify_against_hash(raw_key, self._global_key_hash):
                    return APIKeyInfo(
                        client_id="global",
                        key_hash=self._global_key_hash,
                        is_active=True,
                        description="Global API key",
                    )
            except Exception as exc:
                logger.exception(
                    "Global API key verify unexpected error: %s", exc
                )
                await self._emit_audit_event(
                    event_type="auth.global_verify_error",
                    payload={
                        "error": str(exc),
                        "error_type": type(exc).__name__,
                        "timestamp": str(time.time()),
                    },
                )

        # 2. Проверка per-client ключей в Redis (SCAN + MGET pipeline).
        try:
            import orjson

            from src.backend.infrastructure.clients.storage.redis import (
                get_redis_client as redis_client,
            )

            async def _mget_keys(conn: Any) -> list[dict[str, Any]]:
                keys: list[str] = []
                async for k in conn.scan_iter(match=f"{_KEY_PREFIX}*", count=500):
                    keys.append(k if isinstance(k, str) else k.decode())
                if not keys:
                    return []
                values = await conn.mget(keys)
                result = []
                for v in values:
                    if v is None:
                        continue
                    try:
                        parsed = orjson.loads(v) if isinstance(v, (bytes, str)) else v
                        if isinstance(parsed, dict):
                            result.append(parsed)
                    except Exception as _:
                        logger.debug(
                            "API key Redis value parse failed; skipped", exc_info=True
                        )
                        continue
                return result

            all_data = await redis_client().execute("cache", _mget_keys)  # type: ignore[attr-defined]
            now = time.time()

            for info in all_data:
                stored_hash = info.get("key_hash", "")
                prev_hash = info.get("prev_key_hash", "")
                is_active = info.get("is_active", True)

                if is_active and stored_hash and self._verify_against_hash(
                    raw_key, stored_hash
                ):
                    return APIKeyInfo(
                        client_id=info.get("client_id", "unknown"),
                        key_hash=stored_hash,
                        version=info.get("version", 1),
                        created_at=info.get("created_at", 0),
                        is_active=True,
                    )

                if (
                    prev_hash
                    and is_active
                    and self._verify_against_hash(raw_key, prev_hash)
                    and info.get("rotated_at", 0) + self._grace_period > now
                ):
                    return APIKeyInfo(
                        client_id=info.get("client_id", "unknown"),
                        key_hash=prev_hash,
                        version=info.get("version", 1) - 1,
                        is_active=True,
                        description="grace_period",
                    )

        except Exception as exc:
            logger.warning(
                "Redis key validation error (using global fallback): %s", exc
            )

        return None

    async def create_client_key(self, client_id: str, description: str = "") -> str:
        """Создаёт новый API-ключ для клиента.

        Returns:
            Сгенерированный raw API-ключ (показывается клиенту ОДИН раз).

        Notes:
            S172 M2: stored hash = Argon2id PHC string (с per-key salt).
            Verify path остаётся backward-compat с legacy SHA-256.
        """
        raw_key = f"gd_{secrets.token_urlsafe(32)}"
        key_hash = self._hash_key(raw_key)
        now = time.time()

        key_data = {
            "client_id": client_id,
            "key_hash": key_hash,
            "prev_key_hash": "",
            "version": 1,
            "created_at": now,
            "rotated_at": 0,
            "is_active": True,
            "description": description,
            "hash_algo": "argon2id" if is_argon2_hash(key_hash) else "sha256",
        }

        try:
            import orjson

            from src.backend.infrastructure.clients.storage.redis import (
                get_redis_client as redis_client,
            )

            await redis_client().add_to_stream(  # type: ignore[attr-defined]
                stream_name=_AUDIT_PREFIX + "events",
                data={
                    "event": "create",
                    "client_id": client_id,
                    "hash_algo": key_data["hash_algo"],
                    "timestamp": str(now),
                },
            )

            # Сохраняем в Redis (без TTL — ключ живёт до ротации/удаления)
            await redis_client()._redis.set(  # type: ignore[attr-defined]
                f"{_KEY_PREFIX}{client_id}", orjson.dumps(key_data)
            )
        except Exception as exc:
            logger.error("Failed to store client key: %s", exc)

        logger.info(
            "API key created for client '%s' (v1, hash_algo=%s)",
            client_id,
            key_data["hash_algo"],
        )
        return raw_key

    async def rotate_client_key(self, client_id: str) -> str | None:
        """Ротирует ключ клиента. Старый остаётся в grace period.

        Returns:
            Новый raw API-ключ или None если клиент не найден.

        Notes:
            S172 M2: новый hash — Argon2id. Старый (даже если был Argon2)
            остаётся в ``prev_key_hash`` для grace period.
        """
        try:
            import orjson

            from src.backend.infrastructure.clients.storage.redis import (
                get_redis_client as redis_client,
            )

            raw = await redis_client()._redis.get(f"{_KEY_PREFIX}{client_id}")  # type: ignore[attr-defined]
            if not raw:
                return None

            key_data = orjson.loads(raw)
            old_hash = key_data["key_hash"]

            new_raw = f"gd_{secrets.token_urlsafe(32)}"
            new_hash = self._hash_key(new_raw)
            now = time.time()

            key_data["prev_key_hash"] = old_hash
            key_data["key_hash"] = new_hash
            key_data["version"] = key_data.get("version", 1) + 1
            key_data["rotated_at"] = now
            key_data["hash_algo"] = (
                "argon2id" if is_argon2_hash(new_hash) else "sha256"
            )

            await redis_client()._redis.set(  # type: ignore[attr-defined]
                f"{_KEY_PREFIX}{client_id}", orjson.dumps(key_data)
            )

            await redis_client().add_to_stream(  # type: ignore[attr-defined]
                stream_name=_AUDIT_PREFIX + "events",
                data={
                    "event": "rotate",
                    "client_id": client_id,
                    "version": str(key_data["version"]),
                    "hash_algo": key_data["hash_algo"],
                    "timestamp": str(now),
                },
            )

            logger.info(
                "API key rotated for '%s' (v%d, hash_algo=%s). Grace period: %ds",
                client_id,
                key_data["version"],
                key_data["hash_algo"],
                self._grace_period,
            )
            return new_raw

        except Exception as exc:
            logger.error("Key rotation failed for '%s': %s", client_id, exc)
            return None

    async def revoke_client_key(self, client_id: str) -> bool:
        """Отзывает ключ клиента (немедленно, без grace period)."""
        try:
            from src.backend.infrastructure.clients.storage.redis import (
                get_redis_client as redis_client,
            )

            await redis_client()._redis.delete(f"{_KEY_PREFIX}{client_id}")  # type: ignore[attr-defined]
            await redis_client().add_to_stream(  # type: ignore[attr-defined]
                stream_name=_AUDIT_PREFIX + "events",
                data={
                    "event": "revoke",
                    "client_id": client_id,
                    "timestamp": str(time.time()),
                },
            )
            logger.info("API key revoked for '%s'", client_id)
            return True
        except Exception as exc:
            logger.error("Key revocation failed: %s", exc)
            return False

    async def list_clients(self) -> list[dict[str, Any]]:
        """Список всех зарегистрированных клиентов."""
        try:
            import orjson

            from src.backend.infrastructure.clients.storage.redis import (
                get_redis_client as redis_client,
            )

            result: list[dict[str, Any]] = []
            keys = await redis_client().list_cache_keys(f"{_KEY_PREFIX}*")  # type: ignore[attr-defined]
            for redis_key in keys.get("keys", []):
                raw = await redis_client()._redis.get(redis_key)  # type: ignore[attr-defined]
                if raw:
                    data = orjson.loads(raw)
                    result.append(
                        {
                            "client_id": data.get("client_id"),
                            "version": data.get("version", 1),
                            "is_active": data.get("is_active", True),
                            "created_at": data.get("created_at"),
                            "description": data.get("description", ""),
                            "hash_algo": data.get("hash_algo", "sha256"),
                        }
                    )
            return result
        except Exception as exc:
            logger.error("List clients failed: %s", exc)
            return []

    async def upgrade_to_argon2(
        self, client_id: str, current_raw_key: str
    ) -> bool:
        """Upgrade stored hash для client_id с SHA-256 на Argon2id.

        Требует от caller'а знание current raw key (для re-hash).
        Используется миграционным скриптом.

        Args:
            client_id: ID клиента.
            current_raw_key: Текущий raw API key (для verify).

        Returns:
            ``True`` если upgrade успешен, ``False`` если client не найден
            или verify failed.
        """
        try:
            import orjson

            from src.backend.infrastructure.clients.storage.redis import (
                get_redis_client as redis_client,
            )

            raw = await redis_client()._redis.get(f"{_KEY_PREFIX}{client_id}")  # type: ignore[attr-defined]
            if not raw:
                return False

            key_data = orjson.loads(raw)
            stored_hash = key_data.get("key_hash", "")

            # Verify current raw key против stored hash.
            if not self._verify_against_hash(current_raw_key, stored_hash):
                logger.warning(
                    "upgrade_to_argon2: verify failed for client '%s'", client_id
                )
                return False

            # Re-hash в Argon2id.
            new_hash = self._hasher.hash_key(current_raw_key)
            if not is_argon2_hash(new_hash):
                logger.error(
                    "upgrade_to_argon2: hash returned non-Argon2 format: %r",
                    new_hash[:30],
                )
                return False

            key_data["key_hash"] = new_hash
            key_data["hash_algo"] = "argon2id"
            now = time.time()

            await redis_client()._redis.set(  # type: ignore[attr-defined]
                f"{_KEY_PREFIX}{client_id}", orjson.dumps(key_data)
            )
            await redis_client().add_to_stream(  # type: ignore[attr-defined]
                stream_name=_AUDIT_PREFIX + "events",
                data={
                    "event": "upgrade",
                    "client_id": client_id,
                    "from_algo": "sha256",
                    "timestamp": str(now),
                },
            )
            logger.info("API key upgraded to Argon2id for client '%s'", client_id)
            return True
        except Exception as exc:
            logger.error("upgrade_to_argon2 failed: %s", exc)
            return False


from src.backend.core.di import app_state_singleton


@app_state_singleton("api_key_manager", APIKeyManager)
def get_api_key_manager() -> APIKeyManager:  # type: ignore[empty-body]
    """Возвращает APIKeyManager из app.state или lazy-init fallback."""
