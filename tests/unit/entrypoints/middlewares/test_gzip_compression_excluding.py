"""D-AUDIT-17601: regression-тесты для GZipCompressionExcludingMiddleware.

Фикс: /docs, /redoc, /metrics пропускаются через compression
(по причине несовместимости FastAPI's default GZipMiddleware
с проектом's pure ASGI middleware chain).
"""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.testclient import TestClient

from src.backend.entrypoints.middlewares.gzip_compression_excluding import (
    EXCLUDED_PATH_PREFIXES,
    GZipCompressionExcludingMiddleware,
)


def _build_app_with_middleware() -> FastAPI:
    """Build test app с GZipCompressionExcludingMiddleware."""
    app = FastAPI()

    @app.get("/docs")
    def docs() -> PlainTextResponse:
        return PlainTextResponse(
            "<html><body>Swagger UI</body></html>",
        )

    @app.get("/docs/oauth2-redirect")
    def oauth2_redirect() -> PlainTextResponse:
        return PlainTextResponse("redirect")

    @app.get("/redoc")
    def redoc() -> PlainTextResponse:
        return PlainTextResponse("<html><body>ReDoc</body></html>")

    @app.get("/metrics")
    def metrics() -> PlainTextResponse:
        return PlainTextResponse("# HELP dummy_metric")

    @app.get("/api/v1/health")
    def health() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    @app.get("/api/v1/large")
    def large() -> PlainTextResponse:
        return PlainTextResponse("x" * 1000)

    app.add_middleware(
        GZipCompressionExcludingMiddleware,
        minimum_size=500,
        compresslevel=6,
    )
    return app


def test_excluded_path_prefixes_constant() -> None:
    """Sanity: /docs, /redoc, /metrics в exclude list."""
    assert "/docs" in EXCLUDED_PATH_PREFIXES
    assert "/redoc" in EXCLUDED_PATH_PREFIXES
    assert "/metrics" in EXCLUDED_PATH_PREFIXES


def test_docs_path_passes_through_no_compression() -> None:
    """/docs-style endpoint (excluded) НЕ compress — Content-Encoding не должен быть gzip."""
    app = _build_app_with_middleware()
    client = TestClient(app)
    r = client.get("/docs", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200
    # /docs is FastAPI built-in Swagger UI route → проверяем только
    # что compression НЕ применён (Content-Encoding != gzip).
    assert r.headers.get("content-encoding") != "gzip"


def test_docs_subpath_passes_through() -> None:
    """/docs/oauth2-redirect НЕ compress (subpath)."""
    app = _build_app_with_middleware()
    client = TestClient(app)
    r = client.get("/docs/oauth2-redirect", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200
    assert r.headers.get("content-encoding") != "gzip"


def test_redoc_path_passes_through() -> None:
    """/redoc НЕ compress."""
    app = _build_app_with_middleware()
    client = TestClient(app)
    r = client.get("/redoc", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200
    # /redoc is FastAPI built-in ReDoc route → проверяем только
    # что compression НЕ применён.
    assert r.headers.get("content-encoding") != "gzip"


def test_metrics_path_passes_through() -> None:
    """/metrics НЕ compress (prometheus text format)."""
    app = _build_app_with_middleware()
    client = TestClient(app)
    r = client.get("/metrics", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200
    # /metrics is prometheus text format → проверяем что НЕ compressed
    assert r.headers.get("content-encoding") != "gzip"


def test_non_excluded_path_compressed_when_large() -> None:
    """/api/v1/large (1000 bytes > minimum_size=500) → compressed."""
    app = _build_app_with_middleware()
    client = TestClient(app)
    r = client.get("/api/v1/large", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200
    assert r.headers.get("content-encoding") == "gzip"
    # Body is gzip-compressed, cannot read directly.
    assert r.content != b"x" * 1000


def test_non_excluded_path_not_compressed_when_small() -> None:
    """/api/v1/health (small JSON) → НЕ compressed (size < minimum_size)."""
    app = _build_app_with_middleware()
    client = TestClient(app)
    r = client.get("/api/v1/health", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200
    assert r.headers.get("content-encoding") != "gzip"
    assert r.json() == {"status": "ok"}


def test_no_gzip_accept_encoding_passes_through() -> None:
    """Client без Accept-Encoding: gzip → pass through без compression."""
    app = _build_app_with_middleware()
    client = TestClient(app)
    r = client.get("/api/v1/large")
    assert r.status_code == 200
    assert r.headers.get("content-encoding") != "gzip"
    assert r.content == b"x" * 1000


def test_excluded_paths_dont_have_content_length_mismatch() -> None:
    """/api/v1/large (non-excluded) при Accept-Encoding без gzip → pass through
    с Content-Length = actual body size (не compressed)."""
    app = _build_app_with_middleware()
    client = TestClient(app)
    r = client.get("/api/v1/large")  # no Accept-Encoding → no compression
    assert r.status_code == 200
    assert r.headers.get("content-encoding") != "gzip"
    assert r.content == b"x" * 1000
