"""Менеджер API-ключей с поддержкой ротации.

Хранит ключи в Redis с версионированием и grace period.
Поддерживает per-client ключи и аудит ротации.

Ключ валиден если:
1. Совпадает с текущим активным ключом клиента, ИЛИ
2. Совпадает с предыдущим ключом в grace period, ИЛИ
3. Совпадает с глобальным ключом из настроек (fallback).
"""

import hashlib
import logging
import secrets
import time
from dataclasses import dataclass, field
from typing import Any

__all__ = ("APIKeyManager", "APIKeyInfo", "get_api_key_manager")

logger = logging.getLogger("security.api_keys")

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

    Хранит ключи в Redis (хешированные SHA-256).
    Grace period: старый ключ валиден N секунд после ротации.
    """

    def __init__(self, grace_period_seconds: int = 86400) -> None:
        self._grace_period = grace_period_seconds
        self._global_key_hash: str | None = None

    def _init_global_key(self) -> None:
        """Кэширует хеш глобального ключа из настроек."""
        if self._global_key_hash is None:
            from app.core.config.settings import settings
            self._global_key_hash = self._hash_key(settings.secure.api_key)

    @staticmethod
    def _hash_key(key: str) -> str:
        return hashlib.sha256(key.encode()).hexdigest()

    async def validate_key(self, raw_key: str) -> APIKeyInfo | None:
        """Проверяет API-ключ.

        Returns:
            APIKeyInfo если ключ валиден, None если нет.
        """
        self._init_global_key()
        key_hash = self._hash_key(raw_key)

        # 1. Проверка глобального ключа (fallback)
        if key_hash == self._global_key_hash:
            return APIKeyInfo(
                client_id="global",
                key_hash=key_hash,
                is_active=True,
                description="Global API key",
            )

        # 2. Проверка per-client ключей в Redis (SCAN + MGET pipeline)
        try:
            from app.infrastructure.clients.redis import redis_client
            import orjson

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
                    except Exception:
                        continue
                return result

            all_data = await redis_client.execute("cache", _mget_keys)
            now = time.time()

            for info in all_data:
                stored_hash = info.get("key_hash", "")
                prev_hash = info.get("prev_key_hash", "")

                if stored_hash == key_hash and info.get("is_active", True):
                    return APIKeyInfo(
                        client_id=info.get("client_id", "unknown"),
                        key_hash=key_hash,
                        version=info.get("version", 1),
                        created_at=info.get("created_at", 0),
                        is_active=True,
                    )

                if (
                    prev_hash == key_hash
                    and info.get("rotated_at", 0) + self._grace_period > now
                ):
                    return APIKeyInfo(
                        client_id=info.get("client_id", "unknown"),
                        key_hash=key_hash,
                        version=info.get("version", 1) - 1,
                        is_active=True,
                        description="grace_period",
                    )

        except Exception as exc:
            logger.warning("Redis key validation error (using global fallback): %s", exc)

        return None

    async def create_client_key(
        self, client_id: str, description: str = ""
    ) -> str:
        """Создаёт новый API-ключ для клиента.

        Returns:
            Сгенерированный raw API-ключ (показывается клиенту ОДИН раз).
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
        }

        try:
            from app.infrastructure.clients.redis import redis_client
            import orjson

            await redis_client.add_to_stream(
                stream_name=_AUDIT_PREFIX + "events",
                data={"event": "create", "client_id": client_id, "timestamp": str(now)},
            )

            # Сохраняем в Redis (без TTL — ключ живёт до ротации/удаления)
            await redis_client._redis.set(
                f"{_KEY_PREFIX}{client_id}",
                orjson.dumps(key_data),
            )
        except Exception as exc:
            logger.error("Failed to store client key: %s", exc)

        logger.info("API key created for client '%s' (v1)", client_id)
        return raw_key

    async def rotate_client_key(self, client_id: str) -> str | None:
        """Ротирует ключ клиента. Старый остаётся в grace period.

        Returns:
            Новый raw API-ключ или None если клиент не найден.
        """
        try:
            from app.infrastructure.clients.redis import redis_client
            import orjson

            raw = await redis_client._redis.get(f"{_KEY_PREFIX}{client_id}")
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

            await redis_client._redis.set(
                f"{_KEY_PREFIX}{client_id}",
                orjson.dumps(key_data),
            )

            await redis_client.add_to_stream(
                stream_name=_AUDIT_PREFIX + "events",
                data={
                    "event": "rotate",
                    "client_id": client_id,
                    "version": str(key_data["version"]),
                    "timestamp": str(now),
                },
            )

            logger.info(
                "API key rotated for '%s' (v%d). Grace period: %ds",
                client_id, key_data["version"], self._grace_period,
            )
            return new_raw

        except Exception as exc:
            logger.error("Key rotation failed for '%s': %s", client_id, exc)
            return None

    async def revoke_client_key(self, client_id: str) -> bool:
        """Отзывает ключ клиента (немедленно, без grace period)."""
        try:
            from app.infrastructure.clients.redis import redis_client

            await redis_client._redis.delete(f"{_KEY_PREFIX}{client_id}")
            await redis_client.add_to_stream(
                stream_name=_AUDIT_PREFIX + "events",
                data={"event": "revoke", "client_id": client_id, "timestamp": str(time.time())},
            )
            logger.info("API key revoked for '%s'", client_id)
            return True
        except Exception as exc:
            logger.error("Key revocation failed: %s", exc)
            return False

    async def list_clients(self) -> list[dict[str, Any]]:
        """Список всех зарегистрированных клиентов."""
        try:
            from app.infrastructure.clients.redis import redis_client
            import orjson

            result: list[dict[str, Any]] = []
            keys = await redis_client.list_cache_keys(f"{_KEY_PREFIX}*")
            for redis_key in keys.get("keys", []):
                raw = await redis_client._redis.get(redis_key)
                if raw:
                    data = orjson.loads(raw)
                    result.append({
                        "client_id": data.get("client_id"),
                        "version": data.get("version", 1),
                        "is_active": data.get("is_active", True),
                        "created_at": data.get("created_at"),
                        "description": data.get("description", ""),
                    })
            return result
        except Exception as exc:
            logger.error("List clients failed: %s", exc)
            return []


from app.core.di import app_state_singleton


@app_state_singleton("api_key_manager", APIKeyManager)
def get_api_key_manager() -> APIKeyManager:
    """Возвращает APIKeyManager из app.state или lazy-init fallback."""
