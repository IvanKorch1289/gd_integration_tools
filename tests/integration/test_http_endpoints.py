"""Functional HTTP testing через httpx AsyncClient + ASGI transport.

Используем ASGI transport in-process — не нужен реальный HTTP-сервер
и обход CSRF/auth. Проверяем, что endpoints корректно registered
и возвращают ожидаемые коды.
"""

from __future__ import annotations

import os
import sys

# Repo root в sys.path для extensions/testkit
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# Eager imports чтобы избежать проблем с submodule lazy loading
os.environ.setdefault("APP_PROFILE", " ")
os.environ.setdefault("VAULT_ENABLED", "false")
os.environ.setdefault("DATABASE_HOST", "127.0.0.1")
os.environ.setdefault("DB_NAME", "gd_integration")


def test_openapi_schema_loads() -> bool:
    """OpenAPI schema генерируется без ошибок (через живой backend)."""
    import shutil
    import subprocess

    curl_bin = shutil.which("curl")
    if not curl_bin:
        return False
    try:
        result = subprocess.run(  # noqa: S603
            [curl_bin, "-sS", "-o", "/dev/null", "-w", "%{http_code}",
             "-m", "10", "http://localhost:8000/openapi.json"],
            capture_output=True, text=True, check=True,
        )
        return result.stdout.strip() == "200"
    except Exception:
        return False


def test_health_endpoint_works() -> bool:
    """GET /health — публичный endpoint (no auth)."""
    try:
        import httpx

        with httpx.Client(base_url="http://localhost:8000", timeout=5.0) as client:
            r = client.get("/health")
            return r.status_code == 200 and "status" in r.json()
    except Exception:
        return False


def test_metrics_endpoint_works() -> bool:
    """GET /metrics — Prometheus endpoint (no auth)."""
    try:
        import httpx

        with httpx.Client(base_url="http://localhost:8000", timeout=5.0) as client:
            r = client.get("/metrics")
            return r.status_code == 200 and "python_info" in r.text
    except Exception:
        return False


def test_admin_endpoints_registered() -> bool:
    """/api/v1/admin/* endpoints существуют в OpenAPI."""
    import json
    import shutil
    import subprocess

    curl_bin = shutil.which("curl")
    if not curl_bin:
        return False
    try:
        result = subprocess.run(  # noqa: S603
            [curl_bin, "-sS", "-m", "10", "http://localhost:8000/openapi.json"],
            capture_output=True, text=True, check=True,
        )
        spec = json.loads(result.stdout)
    except Exception:
        return False
    paths = spec.get("paths", {})
    admin_paths = [p for p in paths if "/api/v1/admin/" in p]
    specific = [
        "/api/v1/admin/system-info",
        "/api/v1/admin/services",
        "/api/v1/admin/feature-flags",
    ]
    return all(p in paths for p in specific) and len(admin_paths) >= 50


def test_dsl_routes_registered() -> bool:
    """/api/v1/dsl/* endpoints существуют (auto-loop)."""
    import json
    import shutil
    import subprocess

    curl_bin = shutil.which("curl")
    if not curl_bin:
        return False
    try:
        result = subprocess.run(  # noqa: S603
            [curl_bin, "-sS", "-m", "10", "http://localhost:8000/openapi.json"],
            capture_output=True, text=True, check=True,
        )
        spec = json.loads(result.stdout)
    except Exception:
        return False
    paths = spec.get("paths", {})
    auto_paths = [p for p in paths if "/api/v1/auto/" in p]
    dsl_routes = [p for p in paths if "/dsl-routes" in p]
    return len(auto_paths) > 50 and len(dsl_routes) >= 5


def test_routes_feature_flag_present() -> bool:
    """P2-D8 (audit 2026-08-18): feature_flag step в routes/."""
    import re as _re

    routes_dir = "/home/user/dev/gd_integration_tools/routes"
    routes_with_flag = []
    for root, _, files in os.walk(routes_dir):
        for f in files:
            if f.endswith(".dsl.yaml"):
                content = os.path.join(root, f)
                with open(content, encoding="utf-8") as fh:
                    if _re.search(r"^\s*-\s*feature_flag:", fh.read(), _re.MULTILINE):
                        routes_with_flag.append(content)
    return len(routes_with_flag) >= 4


def test_admin_endpoints_count() -> bool:
    """Подсчёт admin endpoints в OpenAPI (>=100 = все auto-loop подключены)."""
    import json
    import shutil
    import subprocess

    curl_bin = shutil.which("curl")
    if not curl_bin:
        return False
    try:
        result = subprocess.run(  # noqa: S603
            [curl_bin, "-sS", "-m", "10", "http://localhost:8000/openapi.json"],
            capture_output=True, text=True, check=True,
        )
        spec = json.loads(result.stdout)
    except Exception:
        return False
    paths = spec.get("paths", {})
    admin_count = sum(1 for p in paths if "/api/v1/admin/" in p)
    auto_count = sum(1 for p in paths if "/api/v1/auto/" in p)
    dsl_routes_count = sum(1 for p in paths if "/dsl-routes" in p)
    print(f"  [info] admin={admin_count} auto={auto_count} dsl-routes={dsl_routes_count}")
    return admin_count >= 100 and auto_count >= 100 and dsl_routes_count >= 5


def main() -> int:
    tests = [
        ("OpenAPI schema loads", test_openapi_schema_loads),
        ("Health endpoint works", test_health_endpoint_works),
        ("Metrics endpoint works", test_metrics_endpoint_works),
        ("Admin endpoints registered", test_admin_endpoints_registered),
        ("DSL routes registered", test_dsl_routes_registered),
        ("feature_flag step в 4+ routes", test_routes_feature_flag_present),
        ("Admin endpoint count", test_admin_endpoints_count),
    ]
    passed = 0
    failed = 0
    for name, test_fn in tests:
        try:
            if test_fn():
                print(f"  PASS: {name}")
                passed += 1
            else:
                print(f"  FAIL: {name}")
                failed += 1
        except Exception as exc:
            print(f"  ERROR: {name}: {exc}")
            failed += 1
    print(f"\nResults: {passed}/{len(tests)} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
