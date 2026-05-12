"""Глобальный auth-guard middleware (V7 defense-in-depth).

Wave [s2/k1-3-auth-guard]: гарантирует, что **каждый** non-public endpoint
проходит хотя бы один auth-метод (API_KEY / JWT / BASIC / MTLS / SAML /
EXPRESS_JWT). Альтернатива fragile regex-bypass в :class:`APIKeyMiddleware`.

Стратегия:
* публичные пути матчатся по path-prefix allowlist (нормализуются через
  :class:`pathlib.PurePosixPath`);
* для остальных запросов middleware пробует все настроенные верификаторы
  в порядке приоритета; при успехе записывает ``AuthContext`` в
  ``request.state.auth``;
* при провале возвращает 401 без вызова endpoint'а.

Сам middleware **не управляет** конкретными верификаторами — он
импортирует их из :mod:`auth_selector`, чтобы не дублировать логику.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Iterable

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

from src.backend.core.auth import AuthContext, AuthMethod

__all__ = (
    "AuthRequiredMiddleware",
    "DEFAULT_PUBLIC_PATH_PREFIXES",
    "is_path_public",
)


DEFAULT_PUBLIC_PATH_PREFIXES: tuple[str, ...] = (
    "/health",
    "/healthz",
    "/readyz",
    "/livez",
    "/metrics",
    "/asyncapi",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/static",
    "/favicon.ico",
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


class AuthRequiredMiddleware(BaseHTTPMiddleware):
    """Middleware, требующий аутентификацию для всех non-public endpoints.

    Args:
        app: ASGI-приложение.
        public_prefixes: Префиксы путей, для которых auth не требуется.
        accepted_methods: Какие auth-методы пробовать (по умолчанию все).

    Attrs:
        public_prefixes: Текущий allowlist путей.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        public_prefixes: Iterable[str] = DEFAULT_PUBLIC_PATH_PREFIXES,
        accepted_methods: Iterable[AuthMethod] | None = None,
    ) -> None:
        super().__init__(app)
        self.public_prefixes = tuple(public_prefixes)
        self._accepted_methods = (
            tuple(accepted_methods)
            if accepted_methods is not None
            else (
                AuthMethod.API_KEY,
                AuthMethod.JWT,
                AuthMethod.MTLS,
                AuthMethod.SAML,
                AuthMethod.BASIC,
                AuthMethod.EXPRESS_JWT,
            )
        )

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ):
        if is_path_public(request.url.path, self.public_prefixes):
            return await call_next(request)

        if request.method == "OPTIONS":  # CORS preflight
            return await call_next(request)

        ctx = await self._authenticate(request)
        if ctx is None:
            return JSONResponse(
                {"detail": "Authentication required"},
                status_code=401,
            )

        request.state.auth = ctx
        return await call_next(request)

    async def _authenticate(self, request: Request) -> AuthContext | None:
        # Lazy-import: auth_selector тащит heavy DI providers.
        from src.backend.entrypoints.api.dependencies.auth_selector import (
            _VERIFIERS,
        )

        for method in self._accepted_methods:
            verifier = _VERIFIERS.get(method)
            if verifier is None:
                continue
            try:
                ctx = await verifier(request)
            except Exception:  # верификатор не должен ронять middleware
                ctx = None
            if ctx is not None:
                return ctx
        return None
