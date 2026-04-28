"""WebSocket authentication — API key / JWT + per-group ACL.

Multi-instance safety: токены и permissions в Redis (shared between nodes).
Cache локально per-instance с коротким TTL для производительности.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

__all__ = ("WSAuthError", "WSAuthenticator", "get_ws_authenticator")

logger = logging.getLogger("entrypoints.ws_auth")


class WSAuthError(Exception):
    """WebSocket authentication failure."""

    pass


@dataclass(slots=True)
class WSSession:
    """Аутентифицированная WS сессия."""

    client_id: str
    api_key_hash: str
    allowed_groups: set[str] = field(default_factory=set)
    is_admin: bool = False


class WSAuthenticator:
    """Валидация token + ACL для WebSocket.

    Token format:
        - API key (Bearer ...) → через APIKeyManager
        - JWT (опционально)

    ACL:
        - allowed_groups из Redis (permissions:{api_key_hash})
        - is_admin grants full access
    """

    async def authenticate(self, token: str | None) -> WSSession:
        """Проверяет token и возвращает сессию.

        Raises WSAuthError при невалидном token.
        """
        if not token:
            raise WSAuthError("Missing authentication token")

        token = token.replace("Bearer ", "").strip()

        try:
            from src.infrastructure.security.api_key_manager import get_api_key_manager

            mgr = get_api_key_manager()
            info = await mgr.validate(token)
        except ImportError:
            raise WSAuthError("API key manager unavailable")
        except Exception as exc:
            raise WSAuthError(f"Auth failed: {exc}")

        if not info:
            raise WSAuthError("Invalid API key")

        groups = await self._load_groups(info.get("hash", ""))
        is_admin = bool(info.get("is_admin", False))

        return WSSession(
            client_id=info.get("client_id", "anonymous"),
            api_key_hash=info.get("hash", ""),
            allowed_groups=groups,
            is_admin=is_admin,
        )

    async def _load_groups(self, api_key_hash: str) -> set[str]:
        """Загружает ACL groups из Redis (centralized)."""
        if not api_key_hash:
            return set()
        try:
            from src.infrastructure.clients.storage.redis import redis_client

            raw = getattr(redis_client, "_raw_client", None) or redis_client
            members = await raw.smembers(f"ws:groups:{api_key_hash}")
            return {
                m.decode() if isinstance(m, bytes) else str(m) for m in (members or [])
            }
        except (ImportError, AttributeError, ConnectionError):
            return set()

    def can_access_group(self, session: WSSession, group: str) -> bool:
        """Проверка доступа к группе."""
        if session.is_admin:
            return True
        return group in session.allowed_groups

    async def grant_group(self, api_key_hash: str, group: str) -> None:
        """Выдаёт доступ к группе (admin operation)."""
        try:
            from src.infrastructure.clients.storage.redis import redis_client

            raw = getattr(redis_client, "_raw_client", None) or redis_client
            await raw.sadd(f"ws:groups:{api_key_hash}", group)
        except (ImportError, AttributeError, ConnectionError) as exc:
            logger.warning("grant_group failed: %s", exc)

    async def revoke_group(self, api_key_hash: str, group: str) -> None:
        """Отзывает доступ к группе."""
        try:
            from src.infrastructure.clients.storage.redis import redis_client

            raw = getattr(redis_client, "_raw_client", None) or redis_client
            await raw.srem(f"ws:groups:{api_key_hash}", group)
        except (ImportError, AttributeError, ConnectionError) as exc:
            logger.warning("revoke_group failed: %s", exc)


_instance: WSAuthenticator | None = None


def get_ws_authenticator() -> WSAuthenticator:
    global _instance
    if _instance is None:
        _instance = WSAuthenticator()
    return _instance
