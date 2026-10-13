"""Regression test: /docs and /openapi.json get DIFFERENT CSP.

После коммита 2a347ee70 (Sprint 16, fix(entrypoints)) /docs и /redoc
получают relaxed CSP с CDN-allowlist, а /openapi.json (и весь API) —
строгую default-src 'self'. Без этого /docs был пустым в браузере.

Без регрессии, фиксирующей, что эта дифференциация жива:
- re-introduce строгого CSP на /docs сломает Swagger UI;
- re-introduce relaxed CSP на /openapi.json сломает audit / supply-chain
  политики.

Тест использует уже-запущенное приложение или поднимает временно.
"""
from __future__ import annotations
import socket
import subprocess
import time
from pathlib import Path

import pytest
import httpx

REPO = Path(__file__).resolve().parents[2]
# Порядок проверки (предпочитаем dev-сессию на 18008-18009)
KNOWN_PORTS = (18008, 18009, 18000, 8000)


def _free_port() -> int:
    s = socket.socket()
    s.bind(("", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _app_url() -> str:
    """Вернуть URL живого приложения или поднять временно."""
    for port in KNOWN_PORTS:
        try:
            r = httpx.get(f"http://127.0.0.1:{port}/openapi.json", timeout=1.5)
            if r.status_code == 200:
                return f"http://127.0.0.1:{port}"
        except Exception:
            continue
    # Boot own
    port = _free_port()
    proc = subprocess.Popen(
        ["uv", "run", "python", "-m", "uvicorn", "src.backend.main:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=REPO,
        env={"APP_PROFILE": "dev_light", "PATH": "/usr/bin:/bin",
             "HOME": str(Path.home())},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    for _ in range(60):
        try:
            r = httpx.get(f"{base}/openapi.json", timeout=1.0)
            if r.status_code == 200:
                return base
        except Exception:
            pass
        time.sleep(0.5)
    proc.terminate()
    raise RuntimeError(f"app didn't start on port {port}")


@pytest.fixture(scope="module")
def app_url():
    url = _app_url()
    yield url


def test_docs_csp_allows_cdn(app_url: str) -> None:
    """/docs CSP должен разрешать cdn.jsdelivr.net для swagger-ui-bundle.js."""
    r = httpx.head(f"{app_url}/docs", timeout=5.0)
    csp = r.headers.get("content-security-policy", "")
    assert "cdn.jsdelivr.net" in csp, (
        f"/docs CSP must allow cdn.jsdelivr.net for swagger-ui-bundle.js, got: {csp!r}"
    )


def test_redoc_csp_allows_cdn(app_url: str) -> None:
    """/redoc CSP должен разрешать cdn.jsdelivr.net и fonts.googleapis.com."""
    r = httpx.head(f"{app_url}/redoc", timeout=5.0)
    csp = r.headers.get("content-security-policy", "")
    assert "cdn.jsdelivr.net" in csp, (
        f"/redoc CSP must allow cdn.jsdelivr.net, got: {csp!r}"
    )
    assert "fonts.googleapis.com" in csp, (
        f"/redoc CSP must allow fonts.googleapis.com for ReDoc fonts, got: {csp!r}"
    )


def test_openapi_json_csp_is_strict(app_url: str) -> None:
    """/openapi.json CSP должен быть строгим (default-src 'self', без CDN)."""
    r = httpx.head(f"{app_url}/openapi.json", timeout=5.0)
    csp = r.headers.get("content-security-policy", "")
    assert "cdn.jsdelivr.net" not in csp, (
        f"/openapi.json must NOT allow CDN (would leak security boundary), got: {csp!r}"
    )
    assert "default-src 'self'" in csp, (
        f"/openapi.json must have strict default-src 'self', got: {csp!r}"
    )


def test_api_endpoint_csp_is_strict(app_url: str) -> None:
    """Любой /api/v1/ endpoint должен иметь строгую CSP (не CDN)."""
    r = httpx.head(f"{app_url}/api/v1/actions", timeout=5.0)
    csp = r.headers.get("content-security-policy", "")
    assert "cdn.jsdelivr.net" not in csp, (
        f"/api/* CSP must be strict, got: {csp!r}"
    )
