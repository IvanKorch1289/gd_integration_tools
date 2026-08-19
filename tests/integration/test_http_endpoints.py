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


def test_layer_violations_zero_new() -> bool:
    """Sprint 3 (audit 2026-08-19): ``tools/check_layers.py`` exits 0."""
    import shutil
    import subprocess

    py = shutil.which("python") or shutil.which("python3")
    if not py:
        return False
    try:
        result = subprocess.run(  # noqa: S603
            [py, "tools/check_layers.py"],
            capture_output=True, text=True, cwd="/home/user/dev/gd_integration_tools",
        )
        return result.returncode == 0 and "Нарушений: 0 новых" in result.stdout
    except Exception:
        return False


def test_bandit_strict_no_high() -> bool:
    """Sprint 3: bandit-strict HIGH = 0 (audit 2026-08-19)."""
    import subprocess
    import sys

    py = sys.executable  # use venv Python (bandit installed)
    try:
        result = subprocess.run(  # noqa: S603
            [py, "-m", "bandit", "-r", "src/backend", "-lll",
             "-c", "pyproject.toml"],
            capture_output=True, text=True,
            cwd="/home/user/dev/gd_integration_tools",
        )
        combined = (result.stdout or "") + (result.stderr or "")
        return "High: 0" in combined
    except Exception:
        return False


def test_adr_index_current() -> bool:
    """Sprint 3: ADR INDEX актуальный (212 files, header отражает count)."""
    import os

    p = "/home/user/dev/gd_integration_tools/docs/adr/INDEX.md"
    if not os.path.exists(p):
        return False
    content = open(p, encoding="utf-8").read()
    # Header line содержит актуальное число ADR-файлов (>=210)
    import re

    match = re.search(r"ADR-файлов:\s*\*\*(\d+)\*\*", content)
    if not match:
        return False
    return int(match.group(1)) >= 210


def test_per_layer_diagnostic_works() -> bool:
    """Sprint 4: per-layer diagnostic запускается (exit 0 без --fail-under-layer)."""
    import subprocess
    import sys

    try:
        result = subprocess.run(  # noqa: S603
            [sys.executable, "tools/coverage/per_layer_diagnostic.py"],
            capture_output=True, text=True,
            cwd="/home/user/dev/gd_integration_tools",
        )
        return result.returncode == 0
    except Exception:
        return False


def test_layer_lint_allowlist_includes_core_lazy_proxies() -> bool:
    """Sprint 3: tools/check_layers.py содержит CORE_LAZY_PROXY_EXCEPTIONS."""

    p = "/home/user/dev/gd_integration_tools/tools/check_layers.py"
    content = open(p, encoding="utf-8").read()
    return "CORE_LAZY_PROXY_EXCEPTIONS" in content and "src.backend.services.auth" in content


def test_ci_bandit_blocking_gate() -> bool:
    """Sprint 3: bandit job в .github/workflows/security.yml теперь blocking."""
    p = "/home/user/dev/gd_integration_tools/.github/workflows/security.yml"
    content = open(p, encoding="utf-8").read()
    # bandit job block: должно быть `continue-on-error: false` (или отсутствие)
    # между "name: Bandit" и следующим "name:" или концом секции.
    bandit_block = content.split("name: Bandit")[1].split("name:")[0]
    return "continue-on-error: false" in bandit_block


def test_bandit_medium_count_trend() -> bool:
    """Sprint 5: bandit MEDIUM count ≤45 (Sprint 3 baseline: 56)."""
    import json as _json
    import subprocess
    import sys

    py = sys.executable
    try:
        result = subprocess.run(  # noqa: S603
            [py, "-m", "bandit", "-r", "src/backend", "-f", "json", "-ll"],
            capture_output=True, text=True,
            cwd="/home/user/dev/gd_integration_tools",
            check=False,  # bandit может exit != 0 при наличии findings
        )
        # Output может быть либо JSON (успех), либо текст (bandit exit != 0).
        # Извлекаем JSON из stdout или stderr.
        stdout = result.stdout
        stderr = result.stderr
        # Bandit prints progress to stderr, JSON to stdout.
        json_start = stdout.find("{")
        if json_start == -1:
            json_start = stderr.find("{")
            stdout = stderr
        if json_start == -1:
            return False
        data = _json.loads(stdout[json_start:])
        med = [r for r in data.get("results", []) if r["issue_severity"] == "MEDIUM"]
        # MEDIUM count ≤ 45 (Sprint 5 reduced from 56 by 11: B314×4,
        # B310×2, B301×2, B615×2, B108×1).
        return len(med) <= 45
    except Exception:
        return False


def test_defusedxml_in_pyproject() -> bool:
    """Sprint 5: defusedxml в pyproject.toml (B314 fix requirement)."""
    p = "/home/user/dev/gd_integration_tools/pyproject.toml"
    return "defusedxml" in open(p, encoding="utf-8").read()


def test_httpx_unified_transport_default_on() -> bool:
    """Sprint 5: unified transport is active (httpx-retries + hishel)."""
    import subprocess
    import sys

    py = sys.executable
    try:
        result = subprocess.run(  # noqa: S603
            [py, "-c",
             "from src.backend.infrastructure.clients.transport.http_httpx import "
             "is_httpx_retries_available, is_hishel_available; "
             "print('OK' if is_httpx_retries_available() and is_hishel_available() else 'OFF')"],
            capture_output=True, text=True,
            cwd="/home/user/dev/gd_integration_tools",
        )
        return "OK" in result.stdout
    except Exception:
        return False


def main() -> int:
    tests = [
        ("OpenAPI schema loads", test_openapi_schema_loads),
        ("Health endpoint works", test_health_endpoint_works),
        ("Metrics endpoint works", test_metrics_endpoint_works),
        ("Admin endpoints registered", test_admin_endpoints_registered),
        ("DSL routes registered", test_dsl_routes_registered),
        ("feature_flag step в 4+ routes", test_routes_feature_flag_present),
        ("Admin endpoint count", test_admin_endpoints_count),
        ("Layer violations 0 new", test_layer_violations_zero_new),
        ("Bandit-strict HIGH = 0", test_bandit_strict_no_high),
        ("ADR INDEX актуальный", test_adr_index_current),
        ("Per-layer diagnostic works", test_per_layer_diagnostic_works),
        ("Layer lint includes CORE_LAZY_PROXY_EXCEPTIONS", test_layer_lint_allowlist_includes_core_lazy_proxies),
        ("CI bandit blocking gate", test_ci_bandit_blocking_gate),
        ("Bandit MEDIUM count ≤ 45 (Sprint 5 target)", test_bandit_medium_count_trend),
        ("defusedxml в pyproject.toml", test_defusedxml_in_pyproject),
        ("httpx unified transport default ON", test_httpx_unified_transport_default_on),
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
