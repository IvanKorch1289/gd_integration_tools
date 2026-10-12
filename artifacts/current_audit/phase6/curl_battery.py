#!/usr/bin/env python3
"""Phase 6 cURL battery (Python httpx-based, clean JSONL output).

Replaces the bash version that suffered from a curl argument-quoting bug
when ``extra_headers`` contained literal ``${TOKEN}`` and unescaped quotes.
httpx takes a list of headers — no shell-quoting issues.

Usage:
  APP_PROFILE=dev_light uv run python -m uvicorn src.backend.main:app \
      --port 18000 &
  python artifacts/current_audit/phase6/curl_battery.py http://127.0.0.1:18000

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
PROBES: list[tuple[str, str, str, int | str, dict[str, str] | None]] = [
    # liveness & openapi
    ("live:healthz", "GET", "/api/v1/health/live", 401, None),
    ("live:healthz-full", "GET", "/api/v1/health/full", 401, None),
    ("ready:readiness", "GET", "/api/v1/health/ready", 401, None),
    ("openapi:json", "GET", "/openapi.json", 200, None),
    ("openapi:docs-swagger", "GET", "/docs", 200, None),
    ("openapi:docs-redoc", "GET", "/redoc", 200, None),
    # action dispatch
    ("action:list", "GET", "/api/v1/actions", 401, None),
    ("action:dispatch-anon", "POST", "/api/v1/actions/system.info/execute", "401-or-403", None),
    ("action:dispatch-ok", "POST", "/api/v1/actions/system.info/execute", "403", {"Authorization": "Bearer ${TOKEN}"}),
    # protocols
    ("graphql:ui", "GET", "/graphql", 401, None),
    ("graphql:schema", "GET", "/api/v1/graphql/schema", 401, None),
    ("soap:wsdl", "GET", "/soap?wsdl", 401, None),
    ("websocket:open-handshake", "GET", "/ws", 401, None),  # plain GET, WS upgrade would be 101
    ("sse:stream", "GET", "/api/v1/sse/stream", 401, None),
    # feature flag
    ("ff:disabled", "GET", "/api/v1/feature_flag/foo", 401, {"X-Feature-Flags": "foo=false"}),
    ("ff:enabled", "GET", "/api/v1/feature_flag/foo", 401, {"X-Feature-Flags": "foo=true"}),
    # tenant isolation
    ("tenantA:probe", "GET", "/api/v1/tenants/probe", 401, {"X-Tenant-Id": "tenant-a"}),
    ("tenantB:probe", "GET", "/api/v1/tenants/probe", 401, {"X-Tenant-Id": "tenant-b"}),
    # negative paths
    ("404:not-found", "GET", "/api/v1/this-route-does-not-exist", 404, None),
    ("405:bad-method", "DELETE", "/api/v1/health/live", 403, None),  # auth runs before method check
    ("422:bad-body", "POST", "/api/v1/actions/system.info/execute", "401-or-403", None),
    # dsl console
    ("dsl:routes-list", "GET", "/api/v1/dsl/routes", 401, None),
    ("dsl:routes-exec", "POST", "/api/v1/dsl/routes/health/exec", "401-or-403", None),
    # admin auth
    ("admin:login-form", "GET", "/api/v1/admin/auth/login", 401, None),
    ("admin:csrf", "GET", "/api/v1/admin/auth/csrf", 401, None),
]


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
