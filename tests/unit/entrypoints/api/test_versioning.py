"""Tests for API versioning (entrypoints/api/versioning.py).

Wave: [tech-debt/coverage].
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import Response

from src.backend.entrypoints.api.versioning import (
    APIVersion,
    DeprecationMiddleware,
    VersionedRouter,
)


class TestAPIVersion:
    """Tests for APIVersion dataclass."""

    def test_defaults(self) -> None:
        v = APIVersion(version="v1")
        assert v.version == "v1"
        assert v.deprecated is False
        assert v.sunset_date is None
        assert v.migration_url is None
        assert v.description == ""

    def test_full_fields(self) -> None:
        v = APIVersion(
            version="v1",
            deprecated=True,
            sunset_date="2026-01-01",
            migration_url="https://example.com/v2",
            description="Legacy API",
        )
        assert v.deprecated is True
        assert v.sunset_date == "2026-01-01"
        assert v.migration_url == "https://example.com/v2"


class TestVersionedRouter:
    """Tests for VersionedRouter."""

    def test_prefix_set(self) -> None:
        router = VersionedRouter("v1")
        assert router.prefix == "/api/v1"

    def test_custom_prefix(self) -> None:
        router = VersionedRouter("v1", prefix="/custom/v1")
        assert router.prefix == "/custom/v1"

    def test_api_version_stored(self) -> None:
        router = VersionedRouter("v2", deprecated=True, sunset_date="2026-06-01")
        assert router.api_version.version == "v2"
        assert router.api_version.deprecated is True
        assert router.api_version.sunset_date == "2026-06-01"


class TestDeprecationMiddleware:
    """Tests for DeprecationMiddleware."""

    def _make_request(self, path: str) -> Request:
        scope = {
            "type": "http",
            "method": "GET",
            "path": path,
            "query_string": b"",
            "headers": [],
            "server": ("test", 80),
            "scheme": "http",
        }
        return Request(scope)

    @pytest.mark.anyio
    async def test_no_headers_for_non_deprecated(self) -> None:
        app = FastAPI()
        mw = DeprecationMiddleware(app, {"v1": APIVersion(version="v1")})

        async def call_next(request: Request) -> Response:
            return Response("OK")

        request = self._make_request("/api/v1/test")
        response = await mw.dispatch(request, call_next)
        assert "Deprecation" not in response.headers
        assert "Sunset" not in response.headers

    @pytest.mark.anyio
    async def test_deprecation_header_for_deprecated(self) -> None:
        app = FastAPI()
        mw = DeprecationMiddleware(
            app,
            {"v1": APIVersion(version="v1", deprecated=True, sunset_date="2026-01-01")},
        )

        async def call_next(request: Request) -> Response:
            return Response("OK")

        request = self._make_request("/api/v1/test")
        response = await mw.dispatch(request, call_next)
        assert response.headers.get("Deprecation") == "true"
        assert response.headers.get("Sunset") == "2026-01-01"

    @pytest.mark.anyio
    async def test_link_header_when_migration_url_present(self) -> None:
        app = FastAPI()
        mw = DeprecationMiddleware(
            app,
            {
                "v1": APIVersion(
                    version="v1",
                    deprecated=True,
                    migration_url="https://example.com/v2",
                )
            },
        )

        async def call_next(request: Request) -> Response:
            return Response("OK")

        request = self._make_request("/api/v1/test")
        response = await mw.dispatch(request, call_next)
        link = response.headers.get("Link", "")
        assert 'rel="successor-version"' in link

    @pytest.mark.anyio
    async def test_ignores_other_paths(self) -> None:
        app = FastAPI()
        mw = DeprecationMiddleware(
            app, {"v1": APIVersion(version="v1", deprecated=True)}
        )

        async def call_next(request: Request) -> Response:
            return Response("OK")

        request = self._make_request("/api/v2/test")
        response = await mw.dispatch(request, call_next)
        assert "Deprecation" not in response.headers

    def test_register_version(self) -> None:
        mw = DeprecationMiddleware(FastAPI())
        v = APIVersion(version="v3", deprecated=True)
        mw.register(v)
        assert "v3" in mw._versions
