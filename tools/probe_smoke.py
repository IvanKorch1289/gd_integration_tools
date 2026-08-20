#!/usr/bin/env python3
"""Sprint 17 P1-16: HTTP smoke probe harness для gd_integration_tools.

Проверяет:
1. Public endpoints (no auth) — должны return 200
2. Auth-required endpoints без токена — должны return 401 (fail-closed)
3. K8s probe routes — должны return 200 после P0-2 fix (на OLD коде — 401/404)
4. CSRF behavior на POST — должен return 403 csrf_token_missing (security)

Использование:
    python tools/probe_smoke.py [BASE_URL]

Default: http://localhost:8000
"""
from __future__ import annotations

import sys
from collections.abc import Iterable
from dataclasses import dataclass, field

import httpx

DEFAULT_BASE = "http://localhost:8000"
TIMEOUT_S = 3.0


@dataclass
class ProbeResult:
    """Single HTTP probe result."""

    name: str
    method: str
    path: str
    expected: int | tuple[int, ...]
    actual: int = 0
    detail: str = ""
    passed: bool = field(default=False)

    def evaluate(self) -> None:
        """Recompute passed based on current actual vs expected.

        Called after actual is set (post-request).
        """
        if isinstance(self.expected, int):
            self.passed = self.actual == self.expected
        else:
            self.passed = self.actual in self.expected


@dataclass
class ProbeReport:
    """Aggregate smoke probe report."""

    base_url: str
    results: list[ProbeResult] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r.passed)

    def print(self) -> None:
        """Print report в human-readable формат."""
        print(f"\n{'=' * 70}")
        print(f"HTTP Smoke Probe: {self.base_url}")
        print(f"{'=' * 70}")
        for r in self.results:
            status = "PASS" if r.passed else "FAIL"
            print(f"  [{status}] {r.method:6s} {r.path:35s} → {r.actual} (expected {r.expected})")
            if not r.passed and r.detail:
                print(f"         detail: {r.detail[:80]}")
        print(f"\n{'=' * 70}")
        print(f"Summary: {self.passed}/{len(self.results)} PASS, {self.failed} FAIL")
        print(f"{'=' * 70}\n")


def run_probes(base_url: str) -> ProbeReport:
    """Run all smoke probes against base_url."""
    report = ProbeReport(base_url=base_url)

    # 1. Public endpoints — должны быть 200 (no auth)
    #    Note: root "/" is auth-required per current config (admin-only home page)
    public_paths = [
        ("/health", "Liveness probe (raw)"),
        ("/health/live", "Liveness alias (K8s convention)"),
        ("/ready", "Readiness probe"),
        ("/health/ready", "Readiness alias"),
        ("/healthz", "K8s livenessProbe alias (P0-2 fix)"),
        ("/readyz", "K8s readinessProbe alias (P0-2 fix)"),
        ("/livez", "K8s liveness alias (P0-2 fix)"),
        ("/metrics", "Prometheus metrics"),
        ("/docs", "Swagger UI"),
        ("/redoc", "ReDoc UI"),
        ("/openapi.json", "OpenAPI schema"),
        ("/api/v1/auth/methods", "Auth methods (public per spec)"),
    ]
    for path, name in public_paths:
        result = probe_get(base_url, path, name, expected=200)
        report.results.append(result)

    # 2. K8s probes specific check (P0-2 fix)
    #    - В OLD коде: /healthz → 401 (allowlisted, no route, falls through to auth)
    #    - В NEW коде (после redeploy): /healthz → 200 (route registered)
    #    - Это критично для production K8s probes
    k8s_probes = [
        ("/healthz", "P0-2 K8s livenessProbe"),
        ("/readyz", "P0-2 K8s readinessProbe"),
        ("/livez", "P0-2 K8s liveness alias"),
    ]
    for path, name in k8s_probes:
        result = probe_get(base_url, path, name, expected=200)
        # Mark expected for old-code scenario
        result.detail = "P0-2 fix: route должен быть 200 (was 401/404 before fix)"
        report.results.append(result)

    # 3. Auth-required GET endpoints — должны fail-closed (401)
    auth_required_get = [
        ("/api/v1/health/components", "Health components (auth)"),
        ("/api/v1/health/liveness", "Liveness (auth)"),
        ("/api/v1/health/readiness", "Readiness (auth)"),
        ("/api/v1/admin/system-info", "Admin system info"),
        ("/graphql", "GraphQL (GET)"),
        ("/soap/wsdl", "SOAP WSDL"),
    ]
    for path, name in auth_required_get:
        result = probe_get(base_url, path, name, expected=(401, 403))
        report.results.append(result)

    # 4. Auth-required POST endpoints — должны fail-closed (401 или 403 csrf)
    auth_required_post = [
        ("/api/v1/dsl/dispatch", "DSL dispatch"),
        ("/api/v1/orders/", "REST CRUD orders"),
        ("/sse/something", "SSE"),
        ("/ws/something", "WebSocket"),
    ]
    for path, name in auth_required_post:
        result = probe_post(base_url, path, name, expected=(401, 403))
        report.results.append(result)

    return report


def probe_get(
    base_url: str, path: str, name: str, expected: int | tuple[int, ...]
) -> ProbeResult:
    """GET probe with result collection."""
    result = ProbeResult(name=name, method="GET", path=path, expected=expected)
    try:
        with httpx.Client(timeout=TIMEOUT_S) as client:
            response = client.get(f"{base_url}{path}")
        result.actual = response.status_code
        if result.actual >= 500:
            result.detail = response.text[:200]
    except Exception as exc:
        result.actual = 0
        result.detail = f"Exception: {exc}"
    result.evaluate()
    return result


def probe_post(
    base_url: str, path: str, name: str, expected: int | tuple[int, ...]
) -> ProbeResult:
    """POST probe with result collection."""
    result = ProbeResult(name=name, method="POST", path=path, expected=expected)
    try:
        with httpx.Client(timeout=TIMEOUT_S) as client:
            response = client.post(
                f"{base_url}{path}",
                json={},
            )
        result.actual = response.status_code
        if result.actual >= 500:
            result.detail = response.text[:200]
    except Exception as exc:
        result.actual = 0
        result.detail = f"Exception: {exc}"
    result.evaluate()
    return result


def main(args: Iterable[str] = ()) -> int:
    """CLI entry point."""
    base_url = next(iter(args), DEFAULT_BASE)
    report = run_probes(base_url)
    report.print()
    return 0 if report.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
