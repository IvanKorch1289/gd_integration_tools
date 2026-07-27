from __future__ import annotations

"""CSRF Protection Middleware (S184).

Защищает от Cross-Site Request Forgery атак для cookie-based auth.
Критично для банковской шины где используются cookies (Express sessions).

Стратегия (Double-Submit Cookie pattern):
1. На safe methods (GET, HEAD, OPTIONS) — пропускаем
2. На state-changing methods (POST, PUT, PATCH, DELETE) — проверяем:
   - Header ``X-CSRF-Token`` или field ``csrf_token`` в body
   - Должен совпадать с cookie ``csrf_token``
3. API key auth (Bearer/ApiKey headers) — exempt (не использует cookies)
4. JWT auth (Authorization: Bearer) — exempt

References:
- OWASP CSRF Prevention Cheat Sheet
- RFC 7231/7234 (SameSite cookies)
- Master Prompt §3.3 (banking security)
"""


import hmac
from collections.abc import Iterable
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

__all__ = ("CSRFMiddleware",)


class CSRFMiddleware(BaseHTTPMiddleware):
    """CSRF protection для cookie-based auth (S184).

    Использует Double-Submit Cookie pattern:
    - Server sets ``csrf_token`` cookie при первом запросе
    - Client должен echo тот же token в ``X-CSRF-Token`` header

    Safe methods (GET, HEAD, OPTIONS) bypass.
    State-changing methods (POST, PUT, PATCH, DELETE) require CSRF check.

    Exempt:
    - API key auth (``Authorization: ApiKey ...`` или ``X-API-Key``)
    - JWT auth (``Authorization: Bearer <jwt>``)
    - Configured safe paths
    """

    SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
    STATE_CHANGING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

    def __init__(
        self,
        app: ASGIApp,
        *,
        enabled: bool = True,
        safe_paths: Iterable[str] = (),
        cookie_name: str = "csrf_token",
        header_name: str = "X-CSRF-Token",
        body_field: str = "csrf_token",
    ) -> None:
        """Инициализация CSRF middleware.

        Args:
            app: ASGI-приложение.
            enabled: Включить/выключить (для тестов).
            safe_paths: Path prefixes exempt от CSRF check.
            cookie_name: Имя cookie для CSRF token.
            header_name: Имя header для CSRF token.
            body_field: Имя field в body для CSRF token.
        """
        super().__init__(app)
        self._enabled = enabled
        self._safe_paths = tuple(safe_paths)
        self._cookie_name = cookie_name
        self._header_name = header_name.lower()
        self._body_field = body_field

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        """Process request с CSRF check для state-changing methods.

        S192 fix: auto-issue CSRF cookie на safe methods (GET) если cookie
        отсутствует — prevents lockout где client получает 403 без cookie.
        Synchronizer Token Pattern (OWASP recommended).
        """
        if not self._enabled:
            return await call_next(request)

        # Safe methods bypass + auto-issue CSRF cookie
        if request.method in self.SAFE_METHODS:
            response = await call_next(request)
            # S192: auto-issue CSRF token cookie если нет
            if self._cookie_name not in request.cookies:
                import secrets

                token = secrets.token_urlsafe(32)
                # S202 audit fix: ``secure`` от deployment setting, не от
                # request scheme (за TLS proxy ``request.url.scheme == http``
                # → cookie без Secure → MITM downgrade risk).
                from src.backend.core.config.settings import settings

                cookie_secure = getattr(
                    getattr(settings, "secure", None), "cookie_secure", True
                )
                response.set_cookie(
                    self._cookie_name,
                    token,
                    httponly=False,  # readable by JS для header echo
                    secure=cookie_secure,
                    samesite="lax",
                    max_age=3600,
                )
            return response

        # State-changing methods только
        if request.method not in self.STATE_CHANGING_METHODS:
            return await call_next(request)

        # Safe paths bypass (e.g., webhooks)
        if any(request.url.path.startswith(p) for p in self._safe_paths):
            return await call_next(request)

        # API key / JWT auth exempt
        if self._is_token_auth(request):
            return await call_next(request)

        # CSRF check
        cookie_token = request.cookies.get(self._cookie_name)
        header_token = request.headers.get(self._header_name)

        # Header token required + must match cookie
        if not cookie_token or not header_token:
            return JSONResponse(
                {
                    "error": "csrf_token_missing",
                    "detail": f"CSRF token required in cookie and {self._header_name} header",
                },
                status_code=403,
            )

        if not hmac.compare_digest(cookie_token, header_token):
            return JSONResponse(
                {
                    "error": "csrf_token_mismatch",
                    "detail": "CSRF token mismatch between cookie and header",
                },
                status_code=403,
            )

        return await call_next(request)

    def _is_token_auth(self, request: Request) -> bool:
        """Check — request uses token-based auth (not cookie).

        S194 fix: case-insensitive prefix check (RFC 7235 allows lowercase).

        Returns:
            True если использует API key / JWT (exempt от CSRF).
        """
        # Authorization header (case-insensitive Bearer / ApiKey / Token)
        auth_lower = request.headers.get("Authorization", "").lower()
        if auth_lower.startswith(("bearer ", "apikey ", "token ")):
            return True

        # X-API-Key header (case-insensitive)
        if any(
            h.lower() == "x-api-key"
            for h in request.headers.keys()
        ):
            return True

        return False
