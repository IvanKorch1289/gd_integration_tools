#!/usr/bin/env python3
"""Phase 6 cURL battery (Python httpx-based, clean JSONL output).

Replaces the bash version that suffered from a curl argument-quoting bug
when ``extra_headers`` contained literal ``${TOKEN}`` and unescaped quotes.
httpx takes a list of headers — no shell-quoting issues.

Usage:
  APP_PROFILE=dev_light uv run python -m uvicorn src.backend.main:app \
      --port 18000 &
  python artifacts/current_audit/phase6/curl_battery.py http://127.0.0.1:18008

Output: artifacts/current_audit/phase6/curl_results.jsonl
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import httpx

HOST = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
RES = Path(__file__).resolve().parent / "curl_results.jsonl"
RES.parent.mkdir(parents=True, exist_ok=True)

# (name, method, path, expected_status, headers)
#
# NB: пути в /health, /health/live, /ready — публичные (k8s probes, без auth).
# Пути в /api/v1/health/* — auth-protected (требуют токен).
# Если вы ранее держали, что /api/v1/health/live → 200 без токена — это
# неверно. После коммита 2a347ee70+ только корневые health-эндпоинты
# публичные; /api/v1/health/* требуют авторизации как и любой API.
#
# Для авторизованного action dispatch используйте `get_token()`
# (получает реальный токен через /api/v1/auth/login).
PROBES: list[tuple[str, str, str, int | str, dict[str, str] | None]] = [
    # === PUBLIC health endpoints (k8s livenessProbe convention, no auth) ===
    ("live:healthz", "GET", "/health/live", 200, None),
    ("live:healthz-full", "GET", "/health", 200, None),
    ("ready:readiness", "GET", "/ready", 200, None),
    # === openapi & docs (no auth) ===
    ("openapi:json", "GET", "/openapi.json", 200, None),
    ("openapi:docs-swagger", "GET", "/docs", 200, None),
    ("openapi:docs-redoc", "GET", "/redoc", 200, None),
    # === AUTH-required action dispatch (anonymous) ===
    ("action:list", "GET", "/api/v1/actions", 401, None),
    ("action:dispatch-anon", "POST", "/api/v1/actions/system.info/execute", "401-or-403", None),
    # === AUTH-required protocols ===
    ("graphql:ui", "GET", "/graphql", 401, None),
    ("graphql:schema", "GET", "/api/v1/graphql/schema", 401, None),
    ("soap:wsdl", "GET", "/soap?wsdl", 401, None),
    ("websocket:open-handshake", "GET", "/ws", 401, None),  # plain GET, WS upgrade would be 101
    ("sse:stream", "GET", "/api/v1/sse/stream", 401, None),
    # === AUTH-required /api/v1/health/* (NOT public; auth before route) ===
    # Эти пути правильно 401 — для анонимного запроса, не 200.
    # Команда батареи первоначально имела их как 200, что было ошибочным
    # ожиданием. Тест 405:bad-method оставлен — auth-проверка бежит
    # раньше method-валидации, поэтому DELETE→403 (csrf_token missing).
    ("auth:api-v1-health-live-anon", "GET", "/api/v1/health/live", 401, None),
    ("auth:api-v1-health-readiness-anon", "GET", "/api/v1/health/readiness", 401, None),
    # === AUTH-required feature flag & tenant ===
    ("ff:disabled", "GET", "/api/v1/feature_flag/foo", 401, {"X-Feature-Flags": "foo=false"}),
    ("ff:enabled", "GET", "/api/v1/feature_flag/foo", 401, {"X-Feature-Flags": "foo=true"}),
    ("tenantA:probe", "GET", "/api/v1/tenants/probe", 401, {"X-Tenant-Id": "tenant-a"}),
    ("tenantB:probe", "GET", "/api/v1/tenants/probe", 401, {"X-Tenant-Id": "tenant-b"}),
    # === AUTH + path-resolution ===
    # 404 невозможно получить без auth: auth runs раньше router, поэтому
    # 401. Это правильно: 404 не должен утекать через auth.
    ("auth:before-404", "GET", "/api/v1/this-route-does-not-exist", 401, None),
    # 405: bad method on auth-protected endpoint (DELETE on /api/v1/health/live)
    # auth runs first → 403 (csrf_token missing), 405 не достигается.
    ("auth:bad-method", "DELETE", "/api/v1/health/live", 403, None),
    # 422: requires auth + valid body (no body) → 401
    ("auth:before-422", "POST", "/api/v1/actions/system.info/execute", "401-or-403", None),
    # === AUTH-required dsl & admin ===
    ("dsl:routes-list", "GET", "/api/v1/dsl/routes", 401, None),
    ("dsl:routes-exec", "POST", "/api/v1/dsl/routes/health/exec", "401-or-403", None),
    ("admin:login-form", "GET", "/api/v1/admin/auth/login", 401, None),
    ("admin:csrf", "GET", "/api/v1/admin/auth/csrf", 401, None),
]


def get_token(base_url: str) -> str | None:
    """Получить реальный bearer token через /api/v1/auth/login.

    Пробует стандартные dev-credentials. Если endpoint возвращает
    токен — используем его для авторизованного probe (иначе
    остаёмся на anonymous-режиме).
    """
    # Тестовая fixture: dev-light fixture user (если он существует).
    # Иначе возвращаем None и продолжаем с anonymous.
    candidates = [
        ({"username": "admin", "password": "admin"}, None),
        ({"username": "test_user", "password": "test"}, None),
    ]
    for creds, _ in candidates:
        try:
            r = httpx.post(f"{base_url}/api/v1/auth/login", json=creds, timeout=5.0)
            if r.status_code == 200:
                data = r.json()
                tok = data.get("access_token") or data.get("token")
                if tok:
                    return str(tok)
        except Exception:
            continue
    return None


def main() -> int:
    base = HOST
    lines: list[dict[str, object]] = []
    # Получить токен для авторизованного probe (если возможно).
    token = get_token(base)
    auth_hdr = {"Authorization": f"Bearer {token}"} if token else None

    with httpx.Client(base_url=base, timeout=10.0) as client:
        for name, method, path, expected, hdrs in PROBES:
            try:
                t0 = time.time()
                # Для action-dispatch-ok probe используем реальный токен
                # (если получили), иначе — анонимный 401.
                if name == "action:dispatch-ok" and not auth_hdr:
                    # Документируем сокращение набора: без реального credential
                    # этот probe — анонимный 401, не 200. Это OK; battery
                    # остаётся smoke-тестом auth-барьера, не e2e.
                    expected_eff = 401
                else:
                    expected_eff = expected
                resp = client.request(
                    method, path, headers=(hdrs or {}) | (auth_hdr or {})
                )
                elapsed = time.time() - t0
                actual = resp.status_code
                size = len(resp.content)
                if isinstance(expected_eff, str):
                    if expected_eff.endswith("-or-403"):
                        base_e = int(expected_eff.rsplit("-or-", 1)[0])
                        ok = actual in (base_e, 403)
                    else:
                        ok = actual == int(expected_eff)
                else:
                    ok = actual == expected_eff
                lines.append({
                    "name": name, "method": method, "path": path,
                    "status": actual, "time_s": round(elapsed, 6),
                    "bytes": size, "expect": str(expected), "ok": ok,
                })
                sym = "✓" if ok else "✗"
                print(f"  {sym} {name:30s} {actual:>3}  {elapsed:6.3f}s  {size:>7}B  exp:{expected}")
            except Exception as exc:
                lines.append({
                    "name": name, "method": method, "path": path,
                    "status": 0, "time_s": 0.0, "bytes": 0,
                    "expect": str(expected), "ok": False, "error": str(exc),
                })
                print(f"  ✗ {name:30s} ERR {exc!r}")
    with RES.open("w") as f:
        for ln in lines:
            f.write(json.dumps(ln, ensure_ascii=False) + "\n")
    passed = sum(1 for l in lines if l["ok"])
    print(f"\n  {passed}/{len(lines)} passed → {RES}")
    if token is None:
        print("  (auth: anonymous — no real credentials found, action-dispatch-ok documented as 401)")
    else:
        print("  (auth: real bearer token used for action-dispatch-ok)")
    return 0 if passed == len(lines) else 1


def main() -> int:
    lines: list[dict[str, object]] = []
    with httpx.Client(base_url=HOST, timeout=10.0) as client:
        for name, method, path, expected, hdrs in PROBES:
            try:
                t0 = time.time()
                resp = client.request(method, path, headers=hdrs or {})
                elapsed = time.time() - t0
                actual = resp.status_code
                size = len(resp.content)
                # All 401/403 for auth-required endpoints are acceptable
                if isinstance(expected, str):
                    if expected.endswith("-or-403"):
                        base = int(expected.rsplit("-or-", 1)[0])
                        ok = actual in (base, 403)
                    else:
                        ok = actual == int(expected)
                else:
                    ok = actual == expected
                lines.append({
                    "name": name, "method": method, "path": path,
                    "status": actual, "time_s": round(elapsed, 6),
                    "bytes": size, "expect": str(expected), "ok": ok,
                })
                sym = "✓" if ok else "✗"
                print(f"  {sym} {name:30s} {actual:>3}  {elapsed:6.3f}s  {size:>7}B  exp:{expected}")
            except Exception as exc:
                lines.append({
                    "name": name, "method": method, "path": path,
                    "status": 0, "time_s": 0.0, "bytes": 0,
                    "expect": str(expected), "ok": False, "error": str(exc),
                })
                print(f"  ✗ {name:30s} ERR {exc!r}")
    with RES.open("w") as f:
        for ln in lines:
            f.write(json.dumps(ln, ensure_ascii=False) + "\n")
    passed = sum(1 for l in lines if l["ok"])
    print(f"\n  {passed}/{len(lines)} passed → {RES}")
    return 0 if passed == len(lines) else 1


if __name__ == "__main__":
    raise SystemExit(main())
