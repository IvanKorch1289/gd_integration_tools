"""WebSocket authentication — facade с тремя механизмами (S172 M1).

Поддерживаемые credential-форматы (по приоритету, см.
:func:`extract_credential`):

1. **Sec-WebSocket-Protocol subprotocol** (приоритет 1):
   ``Sec-WebSocket-Protocol: jwt.<token>`` или ``apikey.<token>``.
   Token пробрасывается через WS upgrade headers (RFC 6455).
2. **Cookie** (приоритет 2): ``auth_session=<jwt_or_apikey>`` — для
   session-aware routes (нужен :attr:`WSSettings.use_cookies`).
3. **Query parameter** ``?token=<token>`` (приоритет 3, только
   при ``WSSettings.allow_query_token=True``) — WARNING в логах.
   Не рекомендуется (token в access logs).

Внутри валидация делегирует в :class:`WSAuthenticator` (API key path —
существующий код) или напрямую в :class:`src.backend.core.auth.jwt_backend.JwtBackend`.

Backward-compat: ``authenticate(token)`` принимает готовый token как
API key (S96 lifecycle).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.backend.core.logging import get_logger

__all__ = (
    "WSAuthError",
    "WSAuthenticator",
    "WSCredential",
    "extract_credential",
    "get_ws_authenticator",
)

logger = get_logger("entrypoints.ws_auth")


# S172 M1: имя cookie для session auth (стандартное).
WS_AUTH_COOKIE_NAME = "auth_session"


class WSAuthError(Exception):
    """WebSocket authentication failure."""

    pass


@dataclass(slots=True)
class WSCredential:
    """Извлечённый credential из WS handshake.

    Attrs:
        token: Raw token (API key или JWT).
        method: ``"api_key"`` или ``"jwt"`` (что попробовать первым).
        source: Откуда извлечён (``"subprotocol"``, ``"cookie"``,
            ``"query"``) — для audit-event.
    """

    token: str
    method: str
    source: str


@dataclass(slots=True)
class WSSession:
    """Аутентифицированная WS сессия.

    Attrs:
        client_id: Идентификатор клиента (для логов/audit).
        api_key_hash: Stable hash для ACL lookup в Redis.
        allowed_groups: Группы, к которым разрешён subscribe.
        is_admin: True — full access, обходит group ACL.
        principal: Реальный идентификатор пользователя (из JWT-claims
            или API key client_id).
        auth_source: Откуда получен credential (``"api_key"`` / ``"jwt"``
            / ``"cookie_jwt"`` / ``"cookie_apikey"``) — для audit.
    """

    client_id: str
    api_key_hash: str
    allowed_groups: set[str] = field(default_factory=set)
    is_admin: bool = False
    principal: str = ""
    auth_source: str = "api_key"


def extract_credential(
    subprotocol: str | None,
    cookies: dict[str, str] | None = None,
    query_token: str | None = None,
    *,
    allow_query: bool = False,
    allow_cookies: bool = True,
) -> WSCredential | None:
    """Извлечь credential из WS handshake sources.

    Args:
        subprotocol: Sec-WebSocket-Protocol header value.
            Поддерживаемые префиксы: ``jwt.<token>``, ``apikey.<token>``.
        cookies: Dict из request cookies (например ``{"auth_session": ...}``).
        query_token: ``?token=...`` query parameter value.
        allow_query: Разрешить ли credential из query.
        allow_cookies: Разрешить ли credential из cookies.

    Returns:
        :class:`WSCredential` если найден, иначе ``None``.

    Examples:
        >>> extract_credential("jwt.eyJhbGc...")
        WSCredential(token='eyJhbGc...', method='jwt', source='subprotocol')
        >>> extract_credential(None, {"auth_session": "abc"})
        WSCredential(token='abc', method='api_key', source='cookie')
    """
    # Приоритет 1: Sec-WebSocket-Protocol.
    if subprotocol:
        subprotocol = subprotocol.strip()
        # Header может быть comma-separated: "chat, jwt.<token>"
        for part in subprotocol.split(","):
            part = part.strip()
            if part.startswith("jwt."):
                return WSCredential(
                    token=part[len("jwt.") :].strip(),
                    method="jwt",
                    source="subprotocol",
                )
            if part.startswith("apikey."):
                return WSCredential(
                    token=part[len("apikey.") :].strip(),
                    method="api_key",
                    source="subprotocol",
                )

    # Приоритет 2: cookie.
    if allow_cookies and cookies:
        raw = cookies.get(WS_AUTH_COOKIE_NAME)
        if raw:
            raw = raw.strip()
            # Если выглядит как JWT (три base64-сегмента через точки) — JWT,
            # иначе API key.
            method = "jwt" if raw.count(".") == 2 else "api_key"
            return WSCredential(
                token=raw,
                method=method,
                source="cookie",
            )

    # Приоритет 3: query (по умолчанию выключен).
    if allow_query and query_token:
        return WSCredential(
            token=query_token.strip(),
            method="api_key",
            source="query",
        )

    return None


class WSAuthenticator:
    """Валидация token + ACL для WebSocket (API key + JWT + cookie facade).

    Token format:
        - API key (Bearer ...) → через APIKeyManager
        - JWT → через JwtBackend (joserfc)

    ACL:
        - allowed_groups из Redis (permissions:{api_key_hash})
        - is_admin grants full access
    """

    async def authenticate(self, token: str | None) -> WSSession:
        """Проверяет token как API key (backward-compat signature).

        Raises:
            WSAuthError: При отсутствии/невалидности token или любой ошибке.

        Notes:
            Backward-compat: ``token`` обрабатывается как API key
            (Bearer-prefix stripping). Для JWT используйте
            :meth:`authenticate_jwt` или :meth:`authenticate_via_facade`.
        """
        if not token:
            raise WSAuthError("Missing authentication token")

        token = token.replace("Bearer ", "").strip()

        try:
            from src.backend.core.di.providers import get_api_key_manager_provider

            mgr = get_api_key_manager_provider()
            info = await mgr.validate(token)
        except ImportError:
            raise WSAuthError("API key manager unavailable")
        except Exception as exc:
            raise WSAuthError(f"Auth failed: {exc}")

        if not info:
            raise WSAuthError("Invalid API key")

        groups = await self._load_groups(info.get("hash", ""))
        is_admin = bool(info.get("is_admin", False))
        client_id = info.get("client_id", "anonymous")
        api_key_hash = info.get("hash", "")

        return WSSession(
            client_id=client_id,
            api_key_hash=api_key_hash,
            allowed_groups=groups,
            is_admin=is_admin,
            principal=client_id,
            auth_source="api_key",
        )

    async def authenticate_jwt(self, token: str) -> WSSession:
        """Верифицировать JWT и построить :class:`WSSession`.

        Args:
            token: JWT (compact JOSE format: ``header.payload.signature``).

        Raises:
            WSAuthError: Если JWT невалиден (expired / bad-sig / claims).
        """
        if not token:
            raise WSAuthError("Missing JWT token")
        try:
            from src.backend.core.auth.jwt_backend import (
                JwtBackend,
                JwtVerificationError,
            )

            backend = JwtBackend()
            claims = backend.decode(token)
        except ImportError as exc:
            raise WSAuthError(f"JWT backend unavailable: {exc}")
        except JwtVerificationError as exc:
            raise WSAuthError(f"JWT verification failed: {exc}")
        except Exception as exc:
            raise WSAuthError(f"JWT decode failed: {exc}")

        if claims is None:
            raise WSAuthError("JWT decode returned None")

        principal = str(claims.get("sub", "")) or "anonymous"
        groups_list = claims.get("groups", [])
        if not isinstance(groups_list, list):
            groups_list = []
        groups = {str(g) for g in groups_list}
        is_admin = bool(claims.get("is_admin", False)) or "admin" in groups

        # Стабильный hash для ACL lookup (совместимость с Redis-форматом).
        api_key_hash = "jwt:" + str(claims.get("jti", principal))

        logger.debug(
            "ws.auth.jwt_verified principal=%s admin=%s groups=%d",
            principal,
            is_admin,
            len(groups),
        )
        return WSSession(
            client_id=principal,
            api_key_hash=api_key_hash,
            allowed_groups=groups,
            is_admin=is_admin,
            principal=principal,
            auth_source="jwt",
        )

    async def authenticate_via_facade(
        self,
        credential: WSCredential,
    ) -> WSSession:
        """Маршрутизация :class:`WSCredential` → соответствующий auth-path.

        Args:
            credential: Извлечённый credential (см. :func:`extract_credential`).

        Returns:
            Аутентифицированная :class:`WSSession`.

        Raises:
            WSAuthError: При ошибке верификации.
        """
        if credential.method == "jwt":
            session = await self.authenticate_jwt(credential.token)
            if credential.source == "cookie":
                session = WSSession(
                    client_id=session.client_id,
                    api_key_hash=session.api_key_hash,
                    allowed_groups=session.allowed_groups,
                    is_admin=session.is_admin,
                    principal=session.principal,
                    auth_source="cookie_jwt",
                )
            return session
        # default: api_key path
        session = await self.authenticate(credential.token)
        if credential.source == "cookie":
            session = WSSession(
                client_id=session.client_id,
                api_key_hash=session.api_key_hash,
                allowed_groups=session.allowed_groups,
                is_admin=session.is_admin,
                principal=session.principal,
                auth_source="cookie_apikey",
            )
        return session

    async def _load_groups(self, api_key_hash: str) -> set[str]:
        """Загружает ACL groups из Redis (centralized)."""
        if not api_key_hash:
            return set()
        try:
            from src.backend.core.di.providers import get_redis_kv_client_provider

            raw = get_redis_kv_client_provider()
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
            from src.backend.core.di.providers import get_redis_kv_client_provider

            raw = get_redis_kv_client_provider()
            await raw.sadd(f"ws:groups:{api_key_hash}", group)
        except (ImportError, AttributeError, ConnectionError) as exc:
            logger.warning("grant_group failed: %s", exc)

    async def revoke_group(self, api_key_hash: str, group: str) -> None:
        """Отзывает доступ к группе."""
        try:
            from src.backend.core.di.providers import get_redis_kv_client_provider

            raw = get_redis_kv_client_provider()
            await raw.srem(f"ws:groups:{api_key_hash}", group)
        except (ImportError, AttributeError, ConnectionError) as exc:
            logger.warning("revoke_group failed: %s", exc)


_instance: WSAuthenticator | None = None


def get_ws_authenticator() -> WSAuthenticator:
    global _instance
    if _instance is None:
        _instance = WSAuthenticator()
    return _instance
