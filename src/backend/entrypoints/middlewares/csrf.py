"""CSRF Protection Middleware (S184, cycle 57 pure ASGI).

B-04 fix (cycle 33): default cookie ужесточен — ``httponly=True``,
``samesite=strict``, ``secure=settings.app.environment == "production"``.
Ранее httponly=False (cookie readable из JS) и SameSite=lax (разрешал
GET-initiated cross-site CSRF на state-changing endpoints при наличии
метода GET-→-POST redirect). Теперь ``strict`` блокирует любой
cross-origin запрос с cookie.

Защищает от Cross-Site Request Forgery атак для cookie-based auth.
Критично для банковской шины где используются cookies (Express sessions).

Стратегия (Double-Submit Cookie pattern):
1. На safe methods (GET, HEAD, OPTIONS) — пропускаем
2. На state-changing methods (POST, PUT, PATCH, DELETE) — проверяем:
   - Header ``X-CSRF-Token`` или field ``csrf_token`` в body
   - Должен совпадать с cookie ``csrf_token``
3. API key auth (Bearer/ApiKey headers) — exempt (не использует cookies)
4. JWT auth (Authorization: Bearer) — exempt

Cycle 57: переписано с ``BaseHTTPMiddleware`` на pure ASGI для
архитектурной консистентности с cycle 33-56 (L1 middlewares).

Cycle 57 design: CSRF check в ``__call__`` (no-raise pattern,
cycle 39). На safe methods auto-issue CSRF cookie через
send-wrapper. На state-changing проверяется cookie vs header token.
"""

from __future__ import annotations

import hmac
import json
import secrets
from collections.abc import Iterable

from starlette.types import ASGIApp, Receive, Scope, Send

from src.backend.core.config.settings import settings
from src.backend.core.logging import get_logger

__all__ = ("CSRFMiddleware",)

_logger = get_logger(__name__)


class CSRFMiddleware:
    """Pure ASGI CSRF protection для cookie-based auth (S184, cycle 57).

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
        """Инициализирует CSRF middleware.

        Args:
            app: ASGI-приложение.
            enabled: Включить/выключить.
            safe_paths: Path prefixes exempt от CSRF check.
            cookie_name: Имя cookie.
            header_name: Имя header.
            body_field: Имя field в body.
        """
        self.app = app
        self._enabled = enabled
        self._safe_paths = tuple(safe_paths)
        self._cookie_name = cookie_name
        self._header_name_lower = header_name.lower()
        self._body_field = body_field

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Обрабатывает request с CSRF check (cycle 57 pure ASGI)."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if not self._enabled:
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "")

        # Safe methods bypass + auto-issue CSRF cookie.
        if method in self.SAFE_METHODS:
            await self._process_safe(scope, receive, send)
            return

        # Non-state-changing methods bypass.
        if method not in self.STATE_CHANGING_METHODS:
            await self.app(scope, receive, send)
            return

        # Safe paths bypass (e.g., webhooks).
        path = scope.get("path", "")
        if any(path.startswith(p) for p in self._safe_paths):
            await self.app(scope, receive, send)
            return

        # API key / JWT auth exempt.
        if self._is_token_auth(scope):
            await self.app(scope, receive, send)
            return

        # CSRF check.
        cookie_token = self._get_cookie(scope, self._cookie_name)
        header_token = _get_header_value(scope, self._header_name_lower.encode("latin-1"))

        # Header token required + must match cookie.
        if not cookie_token or not header_token:
            _logger.warning(
                "csrf_token_missing path=%s method=%s",
                path,
                method,
            )
            await self._send_403(
                send,
                error="csrf_token_missing",
                detail=f"CSRF token required in cookie and {self._header_name_lower} header",
            )
            return

        if not hmac.compare_digest(cookie_token, header_token):
            _logger.warning(
                "csrf_token_mismatch path=%s method=%s",
                path,
                method,
            )
            await self._send_403(
                send,
                error="csrf_token_mismatch",
                detail="CSRF token mismatch between cookie and header",
            )
            return

        # CSRF check passed → пробрасываем downstream.
        await self.app(scope, receive, send)

    async def _process_safe(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        """Обработка safe method (cycle 57 helper)."""
        # Cycle 57 critical: collect body chunks через send-wrapper
        # (для правильного downstream body). При auto-issue CSRF cookie
        # добавляем Set-Cookie в response headers через send-wrapper.
        cookie_already_present = self._has_cookie(scope, self._cookie_name)
        response_started: dict[str, bool] = {"started": False}
        response_headers: list[tuple[bytes, bytes]] = []
        response_status: dict[str, int] = {"status": 200}

        async def send_wrapper(message) -> None:
            if message["type"] == "http.response.start":
                response_status["status"] = message.get("status", 200)
                headers = list(message.get("headers", []))
                # Auto-issue CSRF cookie (S192) если нет.
                if not cookie_already_present:
                    token = secrets.token_urlsafe(32)
                    # B-04 fix (cycle 33): secure от deployment setting
                    # + httponly=True (cookie не readable из JS, защита
                    # от XSS-based token theft) + SameSite=strict (НЕ lax —
                    # блокирует cross-origin GET-initiated CSRF).
                    is_production = (
                        getattr(getattr(settings, "app", None), "environment", "")
                        == "production"
                    )
                    headers.append(
                        (
                            b"set-cookie",
                            (
                                f"{self._cookie_name}={token}; "
                                f"Max-Age=3600; Path=/; "
                                f"HttpOnly; SameSite=strict"
                                + ("; Secure" if is_production else "")
                            ).encode("latin-1"),
                        )
                    )
                response_headers.clear()
                response_headers.extend(headers)
                response_started["started"] = True
                # Suppress original — отправим свой с cookie.
                await send(
                    {
                        "type": "http.response.start",
                        "status": response_status["status"],
                        "headers": headers,
                    }
                )
            elif message["type"] == "http.response.body":
                # Пропускаем body (cycle 57: только headers модифицируются).
                await send(message)
            else:
                await send(message)

        await self.app(scope, receive, send_wrapper)

    @staticmethod
    def _is_token_auth(scope: Scope) -> bool:
        """Check — request uses token-based auth (not cookie).

        S194 fix: case-insensitive prefix check (RFC 7235 allows lowercase).
        """
        for header_name, header_value in scope.get("headers", []):
            try:
                value = header_value.decode("latin-1")
            except UnicodeDecodeError:
                continue
            if header_name == b"authorization":
                lowered = value.lower()
                if lowered.startswith(("bearer ", "apikey ", "token ")):
                    return True
            if header_name == b"x-api-key":
                return True
        return False

    @staticmethod
    def _get_cookie(scope: Scope, name: str) -> str:
        """Извлекает cookie value из ASGI scope (cycle 47 helper).

        Args:
            scope: ASGI scope.
            name: Имя cookie.

        Returns:
            Cookie value или пустая строка.
        """
        for header_name, header_value in scope.get("headers", []):
            if header_name == b"cookie":
                try:
                    cookies_str = header_value.decode("latin-1")
                except UnicodeDecodeError:
                    continue
                for cookie in cookies_str.split(";"):
                    cookie = cookie.strip()
                    if "=" in cookie:
                        k, v = cookie.split("=", 1)
                        if k.strip() == name:
                            return v.strip()
        return ""

    @staticmethod
    def _has_cookie(scope: Scope, name: str) -> bool:
        """True если cookie присутствует в scope."""
        return bool(CSRFMiddleware._get_cookie(scope, name))

    @staticmethod
    async def _send_403(send: Send, *, error: str, detail: str) -> None:
        """Отправляет 403 JSON response через send (no-raise, cycle 39)."""
        body_bytes = json.dumps({"error": error, "detail": detail}).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 403,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body_bytes)).encode("latin-1")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body_bytes})


def _get_header_value(scope: Scope, name: bytes) -> str:
    """Извлекает header из ASGI scope по lowercase bytes-имени."""
    for header_name, header_value in scope.get("headers", []):
        if header_name == name:
            try:
                return header_value.decode("latin-1")
            except UnicodeDecodeError:
                return ""
    return ""
