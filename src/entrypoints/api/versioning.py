"""API Versioning — поддержка v1/v2 с deprecation headers.

Позволяет иметь несколько версий API одновременно:
- /api/v1/... — legacy, с Deprecation/Sunset headers
- /api/v2/... — текущая стабильная

Usage:
    from app.entrypoints.api.versioning import VersionedRouter, APIVersion

    router_v1 = VersionedRouter(version="v1", deprecated=True, sunset_date="2026-01-01")
    router_v2 = VersionedRouter(version="v2")
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

__all__ = (
    "APIVersion",
    "VersionedRouter",
    "DeprecationMiddleware",
)


@dataclass(slots=True)
class APIVersion:
    """Метаданные версии API."""
    version: str
    deprecated: bool = False
    sunset_date: str | None = None  # ISO date: "2026-01-01"
    migration_url: str | None = None
    description: str = ""


class VersionedRouter(APIRouter):
    """FastAPI router с метаданными версии API.

    Автоматически добавляет Deprecation/Sunset/Link headers
    для устаревших версий.
    """

    def __init__(
        self,
        version: str,
        *,
        deprecated: bool = False,
        sunset_date: str | None = None,
        migration_url: str | None = None,
        prefix: str | None = None,
        **kwargs: Any,
    ) -> None:
        self.api_version = APIVersion(
            version=version,
            deprecated=deprecated,
            sunset_date=sunset_date,
            migration_url=migration_url,
        )
        effective_prefix = prefix if prefix is not None else f"/api/{version}"
        super().__init__(prefix=effective_prefix, **kwargs)


class DeprecationMiddleware(BaseHTTPMiddleware):
    """Middleware, добавляющий Deprecation/Sunset/Link headers.

    Срабатывает для путей, начинающихся с deprecated-версий API.
    """

    def __init__(
        self,
        app: ASGIApp,
        versions: dict[str, APIVersion] | None = None,
    ) -> None:
        super().__init__(app)
        self._versions = versions or {}

    def register(self, version: APIVersion) -> None:
        self._versions[version.version] = version

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        response = await call_next(request)

        path = request.url.path
        # Пример: /api/v1/... → "v1"
        for version_str, version in self._versions.items():
            prefix = f"/api/{version_str}/"
            if not path.startswith(prefix):
                continue

            if version.deprecated:
                # RFC 8594 Deprecation header
                response.headers["Deprecation"] = "true"
                if version.sunset_date:
                    response.headers["Sunset"] = version.sunset_date
                if version.migration_url:
                    response.headers["Link"] = (
                        f'<{version.migration_url}>; rel="successor-version"'
                    )
            break

        return response
