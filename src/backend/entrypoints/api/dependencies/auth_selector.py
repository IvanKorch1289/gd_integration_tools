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
    from src.backend.entrypoints.api.dependencies.auth_selector import require_auth, AuthMethod

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

from src.backend.core.auth import AuthContext, AuthMethod

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
        from src.backend.core.di.providers import get_api_key_manager_provider

        manager = get_api_key_manager_provider()
        info = await manager.validate_key(key)
        if info is None:
            return None
        return AuthContext(AuthMethod.API_KEY, info.client_id, {"key_id": info.key_id})
    except Exception as exc:
        logger.warning("API key verify failed: %s", exc)
        return None


async def _verify_jwt(request: Request) -> AuthContext | None:
    """Верификация локального JWT через :class:`JwtBackend` (joserfc).

    Wave [s2/k1-2-jwt-jwks]: ранее использовался ``python-jose``, который
    отсутствовал в pyproject.toml → ``ImportError`` на первом Bearer-запросе
    в prod. Теперь — joserfc через DI-провайдер ``get_jwt_backend_provider``.
    """
    try:
        from src.backend.core.di.providers import get_jwt_backend_provider

        backend = get_jwt_backend_provider()
        return await backend.verify(request)
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
    """Проверка client certificate (mTLS) через :class:`MtlsBackend`.

    Envoy/Nginx с TLS-termination передают:
    * ``X-Client-Cert-Fingerprint`` — sha256 fingerprint;
    * ``X-Client-Cert-Subject`` — subject DN;
    * ``X-Client-Cert`` (опц.) — PEM-encoded для full validation.

    V15 S2: backend выполняет expiry-check и опц. CA-pinning.
    """
    from src.backend.core.auth.mtls_backend import (
        MtlsBackend,
        MtlsVerificationError,
        default_cryptography_parser,
    )

    parser = None
    try:
        parser = default_cryptography_parser()
    except RuntimeError:
        # cryptography не установлена — fallback на headers-only валидацию.
        parser = None

    backend = MtlsBackend(cert_parser=parser)
    try:
        result = backend.verify(request)
    except MtlsVerificationError as exc:
        logger.warning("mTLS verification failed: %s", exc.reason)
        return None
    if result is None:
        return None
    return AuthContext(
        AuthMethod.MTLS,
        principal=str(result["principal"]),
        metadata=result,
    )


async def _verify_saml(request: Request) -> AuthContext | None:
    """Проверка SAML session (V15 S6).

    Полный SP-initiated SSO flow реализован отдельным endpoint'ом
    ``/api/v1/saml/{login,acs,sls}`` (см. :class:`SamlBackend`). Здесь
    верификация лимитирована проверкой signed session-cookie или
    header'а ``X-SAML-Session-ID``, который выставляется ACS-handler'ом
    после успешной обработки SAMLResponse.
    """
    session_id = (
        request.cookies.get("saml_session")
        or request.headers.get("X-SAML-Session-ID")
    )
    if not session_id:
        return None
    # Реальная валидация session_id — в SP-side store (Redis/in-memory).
    # На уровне ядра принимаем cookie как заявку; проверка её подлинности
    # делается middleware'ом. Это согласуется с тем, как сейчас сделано
    # для X-Client-Cert-Fingerprint (доверяем TLS-proxy / SAML-handler'у).
    return AuthContext(
        AuthMethod.SAML,
        principal=session_id,
        metadata={"session_id": session_id},
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
        from src.backend.core.auth.jwt_backend import (
            JwtBackend,
            JwtVerificationError,
        )
        from src.backend.core.config.auth import build_auth_config

        cfg = build_auth_config().express_jwt
        if not cfg.enabled or not cfg.secret_key:
            return None
        backend = JwtBackend(
            algorithms=["HS256"],
            secret=cfg.secret_key,
            audience=cfg.botx_host or None,
            issuer=cfg.bot_id or None,
        )
        try:
            claims = await backend.decode(token)
        except JwtVerificationError as exc:
            logger.warning("Express JWT verify failed: %s", exc)
            return None
        principal = (
            claims.raw.get("sub") or claims.raw.get("huid") or cfg.bot_id
        )
        return AuthContext(AuthMethod.EXPRESS_JWT, str(principal), claims.raw)
    except Exception as exc:
        logger.warning("Express JWT verify failed: %s", exc)
        return None


_VERIFIERS: dict[AuthMethod, Callable[..., Any]] = {
    AuthMethod.API_KEY: _verify_api_key,
    AuthMethod.JWT: _verify_jwt,
    AuthMethod.BASIC: _verify_basic,
    AuthMethod.MTLS: _verify_mtls,
    AuthMethod.SAML: _verify_saml,
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
