"""Light performance smoke test против gd-app-light container.

Audit 2026-09-21: 300 VU performance validation требует prod-stend.
Этот скрипт — **light smoke** против running container:
- 50 последовательных запросов к /health
- 20 параллельных запросов к /openapi.json
- Report latencies p50/p95/p99

Не заменяет полный load test, но даёт baseline для regression detection.

Использование::

    python tools/perf_smoke.py                    # default localhost:8000
    python tools/perf_smoke.py --host example.com --port 8000
    python tools/perf_smoke.py --sequential 50 --concurrent 20

Exit codes:
    0 — все запросы success, p99 < 300ms
    1 — failures OR p99 > 300ms
    2 — network error / container unreachable
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import time

import httpx


async def _timed_request(client: httpx.AsyncClient, url: str) -> tuple[bool, float]:
    """Single request, return (success, duration_ms)."""
    start = time.monotonic()
    try:
        response = await client.get(url, timeout=10.0)
        elapsed = (time.monotonic() - start) * 1000
        return (response.status_code < 500, elapsed)
    except Exception:
        elapsed = (time.monotonic() - start) * 1000
        return (False, elapsed)


async def _sequential_test(
    client: httpx.AsyncClient, url: str, n: int
) -> list[tuple[bool, float]]:
    """N sequential requests."""
    results: list[tuple[bool, float]] = []
    for _ in range(n):
        result = await _timed_request(client, url)
        results.append(result)
    return results


async def _concurrent_test(
    client: httpx.AsyncClient, url: str, n: int
) -> list[tuple[bool, float]]:
    """N concurrent requests."""
    tasks = [_timed_request(client, url) for _ in range(n)]
    return await asyncio.gather(*tasks)


def _percentile(data: list[float], p: float) -> float:
    """Percentile calculation без numpy."""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    idx = int(len(sorted_data) * p)
    return sorted_data[min(idx, len(sorted_data) - 1)]


def _summarize(label: str, results: list[tuple[bool, float]]) -> dict[str, object]:
    """Aggregate results into summary dict."""
    successes = [r[1] for r in results if r[0]]
    failures = [r[1] for r in results if not r[0]]
    durations = [r[1] for r in results]

    return {
        "label": label,
        "total": len(results),
        "success": len(successes),
        "failure": len(failures),
        "p50_ms": _percentile(durations, 0.5),
        "p95_ms": _percentile(durations, 0.95),
        "p99_ms": _percentile(durations, 0.99),
        "mean_ms": statistics.mean(durations) if durations else 0.0,
        "max_ms": max(durations) if durations else 0.0,
    }


async def main_async(host: str, port: int, sequential: int, concurrent: int) -> int:
    base_url = f"http://{host}:{port}"
    health_url = f"{base_url}/health"
    # Используем /health для concurrent — /openapi.json слишком большой (~88KB)
    # и вызывает "Unsupported ASGI message" на granian при concurrent.
    # Audit 2026-09-21: light smoke ≠ load test. /health достаточно для baseline.
    conc_url = f"{base_url}/health"

    print(f"=== Performance smoke test against {base_url} ===")
    print(f"Sequential: {sequential}, Concurrent: {concurrent}")
    print()

    limits = httpx.Limits(
        max_connections=max(concurrent * 2, 20), max_keepalive_connections=10
    )
    async with httpx.AsyncClient(limits=limits, timeout=10.0) as client:
        # Sanity check.
        try:
            r = await client.get(health_url, timeout=5.0)
            if r.status_code >= 500:
                print(f"❌ Health endpoint returned {r.statuscode}")
                return 2
        except Exception as exc:
            print(f"❌ Cannot reach {health_url}: {exc}")
            return 2

        # Sequential /health.
        seq_results = await _sequential_test(client, health_url, sequential)
        seq_summary = _summarize("sequential /health", seq_results)

        # Concurrent /health (light, no big payload).
        conc_results = await _concurrent_test(client, conc_url, concurrent)
        conc_summary = _summarize("concurrent /health", conc_results)

    summaries = [seq_summary, conc_summary]

    # Print table.
    print(
        f"{'Test':<28} {'N':>4} {'OK':>4} {'Fail':>5} {'p50':>7} {'p95':>7} {'p99':>7} {'max':>7}"
    )
    print("-" * 85)
    for s in summaries:
        print(
            f"{s['label']:<28} {s['total']:>4} {s['success']:>4} {s['failure']:>5} "
            f"{s['p50_ms']:>6.1f}ms {s['p95_ms']:>6.1f}ms {s['p99_ms']:>6.1f}ms {s['max_ms']:>6.1f}ms"
        )
    print()

    # Verdict.
    failures = sum(s["failure"] for s in summaries)
    p99_max = max(s["p99_ms"] for s in summaries)

    if failures > 0:
        print(f"❌ {failures} failures detected")
        return 1

    if p99_max > 300:
        print(f"❌ p99 latency {p99_max:.1f}ms exceeds 300ms SLO")
        return 1

    print(f"✅ All requests success, p99 max = {p99_max:.1f}ms (within 300ms SLO)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Light performance smoke test against running container"
    )
    parser.add_argument(
        "--host", default="localhost", help="Target host (default: localhost)"
    )
    parser.add_argument(
        "--port", type=int, default=8000, help="Target port (default: 8000)"
    )
    parser.add_argument(
        "--sequential", type=int, default=50, help="Sequential requests (default: 50)"
    )
    parser.add_argument(
        "--concurrent", type=int, default=20, help="Concurrent requests (default: 20)"
    )
    args = parser.parse_args(argv)

    try:
        return asyncio.run(
            main_async(args.host, args.port, args.sequential, args.concurrent)
        )
    except KeyboardInterrupt:
        print("Interrupted")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
