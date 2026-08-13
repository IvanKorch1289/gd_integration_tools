"""Глобальный auth-guard middleware (V7 defense-in-depth, cycle 43 pure ASGI).

Wave [s2/k1-3-auth-guard]: гарантирует, что **каждый** non-public endpoint
проходит хотя бы один auth-метод (API_KEY / JWT / BASIC / MTLS / SAML /
EXPRESS_JWT). Альтернатива fragile regex-bypass в :class:`APIKeyMiddleware`.

Стратегия:
* публичные пути матчатся по path-prefix allowlist (нормализуются через
  :class:`pathlib.PurePosixPath`);
* для остальных запросов middleware пробует все настроенные верификаторы
  в порядке приоритета; при успехе записывает ``AuthContext`` в
  ``scope['state']['auth']``;
* при провале отправляет 401 через send (no-raise, cycle 39 lesson).

Cycle 43: переписано с ``BaseHTTPMiddleware`` на pure ASGI для
архитектурной консистентности с cycle 33-42 (L1 middlewares).

Cycle 43 design:
- Public-path check в __call__ (читает scope['path']).
- Auth-вызов через ``verify_request`` (read из scope['headers']/method).
- AuthContext записывается в ``scope['state']['auth']`` (вместо
  ``request.state.auth``) — downstream handlers получают через
  ``request.state.auth`` алиасом.
- 401 отправляется через send (no-raise pattern, cycle 39).

Cycle 43 critical: scope['state'] модифицируется в __call__
(до downstream) — auth context доступен downstream-обработчикам
через request.state.auth. Это отличается от cycle 37
(AuthMethodHeader), где state читал из downstream.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import PurePosixPath

from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from src.backend.core.auth import AuthContext, AuthMethod

__all__ = ("DEFAULT_PUBLIC_PATH_PREFIXES", "AuthRequiredMiddleware", "is_path_public")


DEFAULT_PUBLIC_PATH_PREFIXES: tuple[str, ...] = (
    "/health",
    "/healthz",
    "/health/live",
    "/ready",
    "/readyz",
    "/livez",
    "/metrics",
    "/asyncapi",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/static",
    "/favicon.ico",
    # B-04 fix (cycle 33): /api/v1/auth/login удалён из public allowlist.
    # Step-up auth (LoginStepUpMiddleware) требует X-Step-Up-Token header
    # и rate-limits 10 attempts/5min per IP — login НЕ может быть public.
    # /api/v1/auth/methods остаётся public (Login page нужны available
    # methods до аутентификации).
    "/api/v1/auth/methods",
)


def is_path_public(path: str, prefixes: Iterable[str]) -> bool:
    """Возвращает ``True`` если ``path`` начинается с одного из ``prefixes``.

    Нормализация через :class:`PurePosixPath` устраняет ``..`` и двойные
    слэши; матчинг — строгий ``startswith`` на нормализованной строке.
    """
    normalized = str(PurePosixPath(path or "/"))
    for prefix in prefixes:
        norm_prefix = str(PurePosixPath(prefix))
        if normalized == norm_prefix or normalized.startswith(norm_prefix + "/"):
            return True
    return False


class AuthRequiredMiddleware:
    """Pure ASGI middleware: auth-guard для non-public endpoints (cycle 43).

    Поведение:
    1. Извлекает scope['path'] и scope['method'].
    2. Public-path → пробрасывает downstream без auth.
    3. OPTIONS preflight → пробрасывает downstream без auth.
    4. Иначе → вызывает ``verify_request`` для auth.
    5. Успех → записывает ``AuthContext`` в ``scope['state']['auth']``.
    6. Провал → 401 JSON через send (no-raise, cycle 39).

    Args:
        app: ASGI-приложение.
        public_prefixes: Префиксы путей, для которых auth не требуется.
        accepted_methods: Какие auth-методы пробовать (по умолчанию все).

    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        public_prefixes: Iterable[str] = DEFAULT_PUBLIC_PATH_PREFIXES,
        accepted_methods: Iterable[AuthMethod] | None = None,
    ) -> None:
        """Инициализирует middleware.

        Args:
            app: ASGI-приложение.
            public_prefixes: Префиксы путей, для которых auth не требуется.
            accepted_methods: Какие auth-методы пробовать (по умолчанию все).

        """
        self.app = app
        self.public_prefixes = tuple(public_prefixes)
        self._accepted_methods = (
            tuple(accepted_methods)
            if accepted_methods is not None
            else (
                AuthMethod.API_KEY,
                AuthMethod.JWT,
                AuthMethod.EXPRESS_JWT,
            )
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Точка входа ASGI-протокола.

        Non-HTTP scope (``websocket`` / ``lifespan``) пробрасывается
        downstream без auth-проверки.
        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        method = scope.get("method", "")

        # Public path → пробрасываем без auth.
        if is_path_public(path, self.public_prefixes):
            await self.app(scope, receive, send)
            return

        # OPTIONS preflight (CORS) → пробрасываем без auth.
        if method == "OPTIONS":
            await self.app(scope, receive, send)
            return

        # Authenticate.
        # S124 W2: если предыдущий middleware (api_key, jwt, etc.) уже
        # установил scope['state']['auth'], не переписываем — это
        # ломало admin_roles и группы от API-ключа.
        existing_auth = scope.get("state", {}).get("auth") if isinstance(scope.get("state"), dict) else None
        if existing_auth is not None:
            await self.app(scope, receive, send)
            return
        ctx = await self._authenticate(scope, receive)
        if ctx is None:
            # 401 через send (no-raise, cycle 39).
            await self._send_401(send)
            return

        # Устанавливаем AuthContext в scope['state'] для downstream.
        # В BaseHTTPMiddleware версии было request.state.auth — в pure
        # ASGI эквивалент это scope['state']['auth']. FastAPI автоматически
        # алиасит request.state на scope['state'], поэтому downstream
        # handlers получают ctx через request.state.auth без изменений.
        if "state" not in scope:
            scope["state"] = {}
        scope["state"]["auth"] = ctx

        # Auth OK → пробрасываем downstream.
        await self.app(scope, receive, send)

    async def _authenticate(self, scope: Scope, receive: Receive) -> AuthContext | None:
        """Вызывает verify_request для auth (cycle 43 helper).

        Cycle 43: verify_request имеет signature ``(Request, methods)``.
        Конструируем Starlette Request из scope+receive для совместимости
        с public API auth_selector (S93 W3 refactor).
        """
        # S93 W3: public verify_request вместо private _VERIFIERS access.
        from src.backend.core.auth.auth_selector import verify_request

        request = Request(scope, receive=receive)
        return await verify_request(request, methods=self._accepted_methods)

    @staticmethod
    async def _send_401(send: Send) -> None:
        """Отправляет 401 JSON response через send (cycle 39 lesson)."""
        body = json.dumps({"detail": "Authentication required"}).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("latin-1")),
                    (b"www-authenticate", b"Bearer"),
                ],
            },
        )
        await send({"type": "http.response.body", "body": body})
