"""Lightweight async load test scaffold (S55 W5).

Проверяет throughput DSL routes под нагрузкой. Pure stdlib + asyncio.
Запуск: ``python -m tools.loadtest.routes --route-id <id> --rps 100 --duration 30``

Используется в CI perf-job'ах: ``make loadtest-smoke``.

Архитектура:
* ``LoadGenerator`` — spawns N concurrent workers, each making R requests/sec
  в течение duration секунд.
* ``LoadStats`` — собирает latency percentiles, error rate, throughput.
* ``route_loadtest()`` — convenience: create → run → report.

Не требует locust/k6 (overhead). Достаточно для smoke perf-tests
в development + CI. Для production-grade load testing — используйте
k6 / locust / wrk.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import statistics
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

_log = logging.getLogger(__name__)

__all__ = ("LoadGenerator", "LoadStats", "loadtest", "route_loadtest")


@dataclass(slots=True)
class LoadStats:
    """Собранная статистика по load test run."""

    total_requests: int = 0
    successful: int = 0
    failed: int = 0
    duration_s: float = 0.0
    latencies_ms: list[float] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def rps(self) -> float:
        return self.total_requests / self.duration_s if self.duration_s > 0 else 0.0

    @property
    def error_rate(self) -> float:
        return self.failed / self.total_requests if self.total_requests > 0 else 0.0

    @property
    def p50_ms(self) -> float:
        return _percentile(self.latencies_ms, 50)

    @property
    def p95_ms(self) -> float:
        return _percentile(self.latencies_ms, 95)

    @property
    def p99_ms(self) -> float:
        return _percentile(self.latencies_ms, 99)

    def report(self) -> str:
        return (
            f"LoadStats(total={self.total_requests}, success={self.successful}, "
            f"failed={self.failed}, rps={self.rps:.1f}, "
            f"p50={self.p50_ms:.1f}ms, p95={self.p95_ms:.1f}ms, p99={self.p99_ms:.1f}ms, "
            f"error_rate={self.error_rate:.2%})"
        )


def _percentile(values: list[float], p: int) -> float:
    if not values:
        return 0.0
    return statistics.quantiles(values, n=100, method="inclusive")[p - 1]


@dataclass(slots=True)
class LoadGenerator:
    """Async load generator.

    Args:
        target: async callable, вызываемый для каждого request.
            Returns True при success, False/raises при failure.
        rps: target requests per second.
        duration_s: длительность теста в секундах.
        workers: количество concurrent workers (default 10).
    """

    target: Callable[[], Awaitable[bool]]
    rps: float
    duration_s: float
    workers: int = 10

    async def run(self) -> LoadStats:
        stats = LoadStats()
        start = time.monotonic()
        end_at = start + self.duration_s
        interval = 1.0 / self.rps if self.rps > 0 else 0.0

        async def _worker() -> None:
            while time.monotonic() < end_at:
                req_start = time.perf_counter()
                stats.total_requests += 1
                try:
                    ok = await self.target()
                    if ok:
                        stats.successful += 1
                    else:
                        stats.failed += 1
                except Exception as e:
                    stats.failed += 1
                    if len(stats.errors) < 10:
                        stats.errors.append(repr(e)[:120])
                stats.latencies_ms.append((time.perf_counter() - req_start) * 1000.0)
                if interval > 0:
                    await asyncio.sleep(interval)

        workers = [
            asyncio.create_task(_worker(), name=f"loadtest-{i}")
            for i in range(self.workers)
        ]
        await asyncio.gather(*workers, return_exceptions=True)
        stats.duration_s = time.monotonic() - start
        _log.info("LoadGenerator done: %s", stats.report())
        return stats


async def loadtest(
    target: Callable[[], Awaitable[bool]],
    *,
    rps: float = 100.0,
    duration_s: float = 10.0,
    workers: int = 10,
) -> LoadStats:
    """Convenience: создать + запустить LoadGenerator, вернуть stats."""
    gen = LoadGenerator(target=target, rps=rps, duration_s=duration_s, workers=workers)
    return await gen.run()


async def route_loadtest(
    route_id: str,
    *,
    payload: dict[str, Any] | None = None,
    rps: float = 100.0,
    duration_s: float = 10.0,
    workers: int = 10,
) -> LoadStats:
    """Load test для DSL route.

    Использование::

        stats = await route_loadtest("my_route", rps=500, duration_s=30)
        print(stats.report())

    Args:
        route_id: имя зарегистрированного route.
        payload: payload для каждого request (default ``{}``).
        rps: target requests/sec.
        duration_s: длительность.
        workers: concurrent workers.
    """
    from src.backend.dsl.service import get_dsl_service

    body = payload or {}

    async def _target() -> bool:
        try:
            result = await get_dsl_service().dispatch(
                route_id=route_id, body=body, headers={"x-loadtest": "1"}
            )
            return result is not None
        except Exception:
            return False

    return await loadtest(
        target=_target, rps=rps, duration_s=duration_s, workers=workers
    )


# ── CLI ────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="DSL route load test (S55 W5 smoke perf harness)"
    )
    parser.add_argument("--route-id", required=True, help="DSL route ID")
    parser.add_argument("--rps", type=float, default=100.0)
    parser.add_argument("--duration", type=float, default=10.0)
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    stats = asyncio.run(
        route_loadtest(
            args.route_id, rps=args.rps, duration_s=args.duration, workers=args.workers
        )
    )
    print(stats.report())


if __name__ == "__main__":
    main()
