"""Auth Selector — авторизация на выбор для каждого роута.

Варианты (для внутреннего контура):
- NONE — без авторизации (публичные роуты health/metrics)
- API_KEY — по X-API-Key header
- JWT — Bearer token с верификацией
- BASIC — HTTP Basic Auth
- MTLS — mutual TLS (client certificate)
- EXPRESS — авторизация по eXpress HUID (для bot-triggered)
- ANY — любая из настроенных прошла = OK

Usage:
    from src.entrypoints.api.dependencies.auth_selector import require_auth, AuthMethod

    @router.get("/protected", dependencies=[Depends(require_auth(AuthMethod.API_KEY))])
    async def protected(): ...

    @router.get("/multi", dependencies=[Depends(require_auth([AuthMethod.API_KEY, AuthMethod.JWT]))])
    async def multi(): ...

    @router.get("/public", dependencies=[Depends(require_auth(AuthMethod.NONE))])
    async def public(): ...
"""

from __future__ import annotations

import base64
import logging
from typing import Any, Callable

from fastapi import HTTPException, Request

from src.core.auth import AuthContext, AuthMethod

__all__ = ("AuthMethod", "AuthContext", "require_auth", "set_default_auth")

logger = logging.getLogger(__name__)


_default_auth: AuthMethod | list[AuthMethod] = AuthMethod.API_KEY


def set_default_auth(method: AuthMethod | list[AuthMethod]) -> None:
    """Устанавливает авторизацию по умолчанию для всех роутов."""
    global _default_auth
    _default_auth = method


async def _verify_api_key(request: Request) -> AuthContext | None:
    key = request.headers.get("X-API-Key")
    if not key:
        return None
    try:
        # Wave 6.5a: APIKeyManager — через lazy DI provider.
        from src.core.di.providers import get_api_key_manager_provider

        manager = get_api_key_manager_provider()
        info = await manager.validate_key(key)
        if info is None:
            return None
        return AuthContext(AuthMethod.API_KEY, info.client_id, {"key_id": info.key_id})
    except Exception as exc:
        logger.warning("API key verify failed: %s", exc)
        return None


async def _verify_jwt(request: Request) -> AuthContext | None:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth[7:]
    try:
        from jose import jwt

        from src.core.config.settings import settings

        secret = (
            settings.secure.secret_key.get_secret_value()
            if hasattr(settings.secure.secret_key, "get_secret_value")
            else str(settings.secure.secret_key)
        )
        payload = jwt.decode(token, secret, algorithms=[settings.secure.algorithm])
        principal = payload.get("sub", "")
        return AuthContext(AuthMethod.JWT, principal, payload)
    except Exception as exc:
        logger.warning("JWT verify failed: %s", exc)
        return None


async def _verify_basic(request: Request) -> AuthContext | None:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Basic "):
        return None
    try:
        decoded = base64.b64decode(auth[6:]).decode()
        user, _, password = decoded.partition(":")
        if not user or not password:
            return None
        return AuthContext(AuthMethod.BASIC, user, {"auth_type": "basic"})
    except Exception:
        return None


async def _verify_mtls(request: Request) -> AuthContext | None:
    """Проверка client certificate (mTLS).

    Envoy/Nginx передают fingerprint в header X-Client-Cert-Fingerprint.
    """
    fingerprint = request.headers.get("X-Client-Cert-Fingerprint")
    subject = request.headers.get("X-Client-Cert-Subject")
    if not fingerprint:
        return None
    return AuthContext(
        AuthMethod.MTLS,
        principal=subject or fingerprint,
        metadata={"fingerprint": fingerprint, "subject": subject},
    )


async def _verify_express(request: Request) -> AuthContext | None:
    """Авторизация по eXpress HUID header (для bot-triggered запросов)."""
    huid = request.headers.get("X-Express-HUID")
    if not huid:
        return None
    return AuthContext(AuthMethod.EXPRESS, huid, {"huid": huid})


async def _verify_express_jwt(request: Request) -> AuthContext | None:
    """Верификация JWT, выписанного eXpress BotX.

    Проверяет ``Authorization: Bearer <jwt>``, где токен подписан
    ``settings.express.secret_key``. Issuer — ``bot_id``,
    audience — ``botx_host``.
    """
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth[7:]
    try:
        from jose import jwt

        from src.core.config.auth import build_auth_config

        cfg = build_auth_config().express_jwt
        if not cfg.enabled or not cfg.secret_key:
            return None
        options = {"verify_aud": bool(cfg.botx_host)}
        payload = jwt.decode(
            token,
            cfg.secret_key,
            algorithms=["HS256"],
            audience=cfg.botx_host or None,
            issuer=cfg.bot_id or None,
            options=options,
        )
        principal = payload.get("sub") or payload.get("huid") or cfg.bot_id
        return AuthContext(AuthMethod.EXPRESS_JWT, str(principal), payload)
    except Exception as exc:
        logger.warning("Express JWT verify failed: %s", exc)
        return None


_VERIFIERS: dict[AuthMethod, Callable[..., Any]] = {
    AuthMethod.API_KEY: _verify_api_key,
    AuthMethod.JWT: _verify_jwt,
    AuthMethod.BASIC: _verify_basic,
    AuthMethod.MTLS: _verify_mtls,
    AuthMethod.EXPRESS: _verify_express,
    AuthMethod.EXPRESS_JWT: _verify_express_jwt,
}


def require_auth(
    methods: AuthMethod | list[AuthMethod] | None = None,
) -> Callable[[Request], Any]:
    """Factory для FastAPI dependency.

    Args:
        methods: Один метод / список / None (использует default).

    Returns:
        Async dependency возвращающий AuthContext.
    """
    effective = methods if methods is not None else _default_auth

    if isinstance(effective, AuthMethod):
        methods_list = [effective]
    else:
        methods_list = list(effective)

    async def dependency(request: Request) -> AuthContext:
        if AuthMethod.NONE in methods_list:
            return AuthContext(AuthMethod.NONE, "anonymous")

        for method in methods_list:
            verifier = _VERIFIERS.get(method)
            if verifier is None:
                continue
            ctx = await verifier(request)
            if ctx is not None:
                request.state.auth = ctx
                return ctx

        raise HTTPException(
            status_code=401,
            detail=f"Authentication required. Accepted methods: {[m.value for m in methods_list]}",
        )

    return dependency
