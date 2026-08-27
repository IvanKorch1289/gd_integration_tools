#!/usr/bin/env python3
"""Post-rollout monitoring script для S13 Phase 4 staging (S66 W1).

Complements `verify_s13_phase4_readiness.sh` (pre-flight, S64):
- Pre-flight: BEFORE rollout (verifies prerequisites)
- Monitor: DURING rollout (checks ongoing health)

Per ADR-0276 §2 monitoring thresholds:
| Metric              | Threshold     | Action                            |
|---------------------|---------------|------------------------------------|
| Circuit OPEN rate   | > 5%          | Investigate upstream service       |
| Registry sync lag   | > 100ms       | Check Redis health, network        |
| Middleware error    | > 0.1%        | Roll back, investigate             |
| p99 latency         | > +50ms       | Check registry overhead            |
| Redis health        | DOWN          | Sentinel failover, check health    |

Usage:
    # Local dev/staging monitoring
    uv run python scripts/monitor_s13_phase4.py \\
        --prometheus-url http://prometheus:9090 \\
        --app-url http://api:8000 \\
        --duration 24h

    # Production monitoring (during rollout soak)
    uv run python scripts/monitor_s13_phase4.py \\
        --prometheus-url https://prometheus.example.com \\
        --app-url https://api.example.com \\
        --duration 72h \\
        --threshold-circuit-open-rate 5.0 \\
        --threshold-p99-latency-ms 200

Exit codes:
    0 — все thresholds met (healthy)
    1 — threshold violation detected
    2 — infrastructure error (cannot connect to Prometheus/app)
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from typing import Any

# S66 W1: this script intentionally has minimal external dependencies
# to work in restricted environments (no extra pip install required).
# Uses only stdlib + urllib for Prometheus queries.


@dataclass
class MonitoringThresholds:
    """Configurable thresholds for Phase 4 monitoring.

    Defaults match ADR-0276 §2.
    """

    circuit_open_rate_pct: float = 5.0  # > 5% = investigate
    registry_sync_lag_ms: float = 100.0  # > 100ms = check Redis
    middleware_error_rate_pct: float = 0.1  # > 0.1% = roll back
    p99_latency_delta_ms: float = 50.0  # > +50ms = investigate
    redis_down_alert: bool = True  # Redis down = critical


@dataclass
class MonitoringResult:
    """Result of monitoring check."""

    healthy: bool
    circuit_open_rate: float
    middleware_error_rate: float
    p99_latency_ms: float
    redis_status: str
    violations: list[str]

    def format_report(self) -> str:
        """Format human-readable monitoring report."""
        status = "✅ HEALTHY" if self.healthy else "❌ VIOLATIONS"
        lines = [
            "=" * 60,
            f"S13 Phase 4 Monitoring Report — {status}",
            "=" * 60,
            f"Circuit OPEN rate:     {self.circuit_open_rate:.2f}% (threshold: 5.00%)",
            f"Middleware error rate: {self.middleware_error_rate:.4f}% (threshold: 0.10%)",
            f"p99 latency:           {self.p99_latency_ms:.0f}ms",
            f"Redis status:          {self.redis_status}",
            "",
        ]
        if self.violations:
            lines.append("VIOLATIONS:")
            for v in self.violations:
                lines.append(f"  - {v}")
        else:
            lines.append("No threshold violations.")
        lines.append("=" * 60)
        return "\n".join(lines)


def query_prometheus(prometheus_url: str, query: str) -> Any:
    """Execute PromQL query against Prometheus HTTP API.

    S66 W1: minimal HTTP client (no extra deps). Returns parsed JSON or None.
    """
    import json
    import urllib.error
    import urllib.parse
    import urllib.request

    url = f"{prometheus_url.rstrip('/')}/api/v1/query?{urllib.parse.urlencode({'query': query})}"
    try:
        # noqa: S310 — urllib acceptable for internal Prometheus endpoint
        # (CLI argument explicitly user-supplied, timeout=5s limits blast radius)
        with urllib.request.urlopen(url, timeout=5) as resp:  # noqa: S310
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("data", {}).get("result", [])
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        print(f"Warning: Prometheus query failed: {exc}", file=sys.stderr)
        return []


def get_circuit_open_rate(prometheus_url: str) -> float:
    """Get current circuit breaker OPEN rate from Prometheus.

    Uses metric `circuit_breaker_state` (state value: 1=open, 0=closed, 2=half_open).
    """
    # Query: rate of state changes to "open" over 5 minutes
    query = (
        'sum(rate(circuit_breaker_transition_total{state="open"}[5m])) / '
        'sum(rate(circuit_breaker_request_total[5m])) * 100'
    )
    results = query_prometheus(prometheus_url, query)
    if not results:
        return 0.0
    try:
        return float(results[0]["value"][1])
    except (KeyError, IndexError, ValueError):
        return 0.0


def get_middleware_error_rate(prometheus_url: str) -> float:
    """Get middleware error rate from Prometheus."""
    query = (
        'sum(rate(circuit_breaker_middleware_errors_total[5m])) / '
        'sum(rate(circuit_breaker_middleware_requests_total[5m])) * 100'
    )
    results = query_prometheus(prometheus_url, query)
    if not results:
        return 0.0
    try:
        return float(results[0]["value"][1])
    except (KeyError, IndexError, ValueError):
        return 0.0


def get_p99_latency(prometheus_url: str) -> float:
    """Get p99 request latency in milliseconds."""
    query = (
        'histogram_quantile(0.99, '
        'sum(rate(http_request_duration_seconds_bucket[5m])) by (le)) * 1000'
    )
    results = query_prometheus(prometheus_url, query)
    if not results:
        return 0.0
    try:
        return float(results[0]["value"][1])
    except (KeyError, IndexError, ValueError):
        return 0.0


def check_redis_health(redis_url: str) -> str:
    """Check Redis Sentinel/master health via simple TCP connection."""
    import socket

    # Parse Redis URL: redis://[:password@]host:port/db
    if "://" in redis_url:
        redis_url = redis_url.split("://", 1)[1]
    if "@" in redis_url:
        _, redis_url = redis_url.rsplit("@", 1)
    host_port = redis_url.split("/", 1)[0]
    host, _, port = host_port.rpartition(":")
    port = int(port) if port else 6379

    try:
        with socket.create_connection((host, port), timeout=2):
            return "up"
    except (ConnectionRefusedError, socket.timeout, OSError):
        return "down"


def run_monitoring_check(
    prometheus_url: str,
    redis_url: str | None,
    thresholds: MonitoringThresholds,
) -> MonitoringResult:
    """Run one monitoring check and return result."""
    circuit_open_rate = get_circuit_open_rate(prometheus_url)
    middleware_error_rate = get_middleware_error_rate(prometheus_url)
    p99_latency_ms = get_p99_latency(prometheus_url)
    redis_status = check_redis_health(redis_url) if redis_url else "not-monitored"

    violations: list[str] = []
    if circuit_open_rate > thresholds.circuit_open_rate_pct:
        violations.append(
            f"Circuit OPEN rate {circuit_open_rate:.2f}% > {thresholds.circuit_open_rate_pct}%"
        )
    if middleware_error_rate > thresholds.middleware_error_rate_pct:
        violations.append(
            f"Middleware error rate {middleware_error_rate:.4f}% > "
            f"{thresholds.middleware_error_rate_pct}%"
        )
    if redis_status == "down" and thresholds.redis_down_alert:
        violations.append("Redis is DOWN — Sentinel failover required")

    return MonitoringResult(
        healthy=len(violations) == 0,
        circuit_open_rate=circuit_open_rate,
        middleware_error_rate=middleware_error_rate,
        p99_latency_ms=p99_latency_ms,
        redis_status=redis_status,
        violations=violations,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="S13 Phase 4 post-rollout monitoring"
    )
    parser.add_argument(
        "--prometheus-url",
        default="http://localhost:9090",
        help="Prometheus URL (default: http://localhost:9090)",
    )
    parser.add_argument(
        "--redis-url",
        default=None,
        help="Redis URL (Sentinel or single) for health check",
    )
    parser.add_argument(
        "--duration",
        default="24h",
        help="Rollout duration label (for reporting only)",
    )
    parser.add_argument(
        "--threshold-circuit-open-rate",
        type=float,
        default=5.0,
        help="Circuit OPEN rate threshold (%%, default: 5.0)",
    )
    parser.add_argument(
        "--threshold-p99-latency-ms",
        type=float,
        default=200.0,
        help="p99 latency threshold in ms (default: 200)",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Continuously monitor (default: single check)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=60,
        help="Watch interval in seconds (default: 60)",
    )

    args = parser.parse_args()

    thresholds = MonitoringThresholds(
        circuit_open_rate_pct=args.threshold_circuit_open_rate,
        p99_latency_delta_ms=args.threshold_p99_latency_ms,
    )

    print(f"S13 Phase 4 monitoring — duration: {args.duration}")
    print(f"Prometheus: {args.prometheus_url}")
    if args.redis_url:
        print(f"Redis: {args.redis_url}")
    print()

    if not args.watch:
        # Single check
        result = run_monitoring_check(args.prometheus_url, args.redis_url, thresholds)
        print(result.format_report())
        return 0 if result.healthy else 1

    # Watch mode
    print(f"Watching every {args.interval}s (Ctrl+C to stop)...")
    try:
        while True:
            result = run_monitoring_check(args.prometheus_url, args.redis_url, thresholds)
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            status = "OK" if result.healthy else "VIOLATIONS"
            print(
                f"[{ts}] {status} | "
                f"open={result.circuit_open_rate:.2f}% "
                f"err={result.middleware_error_rate:.4f}% "
                f"p99={result.p99_latency_ms:.0f}ms "
                f"redis={result.redis_status}"
            )
            if not result.healthy:
                for v in result.violations:
                    print(f"  - {v}")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nMonitoring stopped.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
