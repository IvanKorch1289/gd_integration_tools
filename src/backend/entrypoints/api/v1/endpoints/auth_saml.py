"""SAML SP-initiated endpoints (Sprint 9 K1 W1).

Эндпоинты:

* ``GET /auth/saml/login`` — инициация SSO, redirect клиента на IdP.
* ``POST /auth/saml/acs`` — Assertion Consumer Service: приём SAMLResponse,
  валидация, выдача session-cookie ``saml_session``.
* ``GET /auth/saml/sls`` — SingleLogoutService (опционально, если IdP
  поддерживает).

Feature-flag: ``feature_flags.saml_sp_initiated_enabled`` (Sprint 9 backbone).
При выключенном флаге endpoints возвращают 503.
"""

from __future__ import annotations

import urllib.parse

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse

from src.backend.core.auth.saml import SamlError, SamlSpHandler
from src.backend.infrastructure.logging.factory import get_logger

__all__ = ("router",)

logger = get_logger(__name__)

router = APIRouter()


def _get_handler(request: Request) -> SamlSpHandler:
    """DI-helper: достаёт :class:`SamlSpHandler` из app.state.

    SAML handler регистрируется в lifespan (см.
    :mod:`plugins.composition.lifecycle`). Если он отсутствует —
    503 (SAML отключён).
    """
    handler = getattr(request.app.state, "saml_sp_handler", None)
    if handler is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SAML SP-initiated flow disabled or not configured",
        )
    return handler


def _is_safe_return_to(url: str, allowed_host: str | None) -> bool:
    """Защита от open-redirect: разрешён только same-origin.

    Args:
        url: URL из ?return_to=...
        allowed_host: текущий host (request.url.hostname). Если None,
            считаем безопасным любой относительный путь.
    """
    if not url:
        return False
    if url.startswith("/") and not url.startswith("//"):
        return True
    parsed = urllib.parse.urlparse(url)
    if not parsed.netloc:
        return True
    return allowed_host is not None and parsed.netloc == allowed_host


@router.get("/login", summary="SAML SP-initiated SSO login")
async def saml_login(
    request: Request, return_to: str | None = None
) -> RedirectResponse:
    """Инициировать SP-initiated SSO.

    Шаги:

    1. ``return_to`` — same-origin URL для post-login redirect (защита
       от open-redirect).
    2. Сгенерировать AuthnRequest ID + RelayState.
    3. 302 → IdP SSO URL с ``SAMLRequest`` + ``RelayState``.
    """
    handler = _get_handler(request)
    safe_target = (
        return_to
        if return_to and _is_safe_return_to(return_to, request.url.hostname)
        else None
    )
    result = handler.initiate_login(return_to=safe_target)
    logger.info(
        "saml.login.initiated",
        extra={"request_id": result.request_id, "relay_state": result.relay_state},
    )
    return RedirectResponse(url=result.redirect_url, status_code=302)


@router.post("/acs", summary="SAML Assertion Consumer Service")
async def saml_acs(request: Request, response: Response) -> dict:
    """Принять SAMLResponse от IdP.

    SAMLResponse + RelayState приходят в form-data (HTTP-POST binding).
    Здесь только верифицируем, валидация подписи делегирована
    handler.consume_acs (через validator-factory из app.state).

    Returns:
        JSON ``{"principal": "...", "session_index": "..."}``.
        Session-cookie ``saml_session`` HttpOnly+Secure выдан в Set-Cookie.

    Raises:
        HTTPException 401: replay, signature invalid, expired.
    """
    handler = _get_handler(request)
    form = await request.form()
    saml_response_b64 = form.get("SAMLResponse")
    relay_state = form.get("RelayState", "/")
    request_id = form.get("InResponseTo") or form.get("RequestID")
    if not saml_response_b64 or not request_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="SAMLResponse and InResponseTo required",
        )

    validator_factory = getattr(request.app.state, "saml_validator_factory", None)
    if validator_factory is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SAML validator not configured",
        )

    def _validator():
        return validator_factory(saml_response_b64=saml_response_b64)

    try:
        auth_result = handler.consume_acs(
            request_id=str(request_id), validator_factory=_validator
        )
    except SamlError as exc:
        logger.warning("saml.acs.rejected", extra={"reason": str(exc)})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"SAML validation failed: {exc}",
        ) from exc

    response.set_cookie(
        "saml_session",
        value=f"{auth_result.principal}|{auth_result.session_index or ''}",
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=3600,
    )
    logger.info(
        "saml.acs.success",
        extra={
            "principal": auth_result.principal,
            "session_index": auth_result.session_index,
        },
    )
    return {
        "principal": auth_result.principal,
        "session_index": auth_result.session_index,
        "redirect_to": str(relay_state) if relay_state else "/",
    }


@router.get("/sls", summary="SAML Single Logout Service")
async def saml_sls(request: Request) -> Response:
    """SLO — invalidate session, redirect на IdP SLO.

    При отсутствии IdP SLO возвращает 200 с очисткой cookie.
    """
    response = Response(status_code=200)
    response.delete_cookie("saml_session")
    return response
