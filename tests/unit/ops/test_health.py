"""Unit tests для src.backend.ops.health.HealthCheck."""

from __future__ import annotations

import asyncio
import socket
import time
from collections.abc import AsyncIterator
from typing import Any

import pytest

from src.backend.ops.health import (
    CheckResult,
    CheckStatus,
    HealthCheck,
    HealthReport,
    HealthStatus,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _free_port() -> int:
    """Найти свободный TCP-порт (и сразу закрыть)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


async def _start_tcp_server() -> tuple[asyncio.AbstractServer, int]:
    """Запустить минимальный TCP-сервер, вернуть (server, port)."""

    async def handler(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:  # noqa: BLE001, S110
            pass
        del reader

    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    return server, int(server.sockets[0].getsockname()[1])


async def _start_http_server() -> tuple[asyncio.AbstractServer, int]:
    """HTTP-сервер, отвечающий 200 OK на любой GET."""

    async def handler(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            await reader.readuntil(b"\r\n\r\n")
        except Exception:  # noqa: BLE001, S110
            pass
        writer.write(
            b"HTTP/1.0 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nOK"
        )
        await writer.drain()
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:  # noqa: BLE001, S110
            pass

    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    return server, int(server.sockets[0].getsockname()[1])


async def _start_http_server_500() -> tuple[asyncio.AbstractServer, int]:
    """HTTP-сервер, отвечающий 500 на любой GET."""

    async def handler(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            await reader.readuntil(b"\r\n\r\n")
        except Exception:  # noqa: BLE001, S110
            pass
        writer.write(
            b"HTTP/1.0 500 Internal\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
        )
        await writer.drain()
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:  # noqa: BLE001, S110
            pass

    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    return server, int(server.sockets[0].getsockname()[1])


@pytest.fixture
async def tcp_pair() -> AsyncIterator[tuple[asyncio.AbstractServer, int]]:
    server, port = await _start_tcp_server()
    try:
        yield server, port
    finally:
        server.close()
        await server.wait_closed()


@pytest.fixture
async def http_pair() -> AsyncIterator[tuple[asyncio.AbstractServer, int]]:
    server, port = await _start_http_server()
    try:
        yield server, port
    finally:
        server.close()
        await server.wait_closed()


@pytest.fixture
async def http_500_pair() -> AsyncIterator[tuple[asyncio.AbstractServer, int]]:
    server, port = await _start_http_server_500()
    try:
        yield server, port
    finally:
        server.close()
        await server.wait_closed()


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_add_http() -> None:
    hc = HealthCheck()
    hc.add_http("api", "http://example.com/ping")
    assert "api" in hc._checks
    assert hc._checks["api"].kind == "http"


def test_add_tcp() -> None:
    hc = HealthCheck()
    hc.add_tcp("redis", "localhost", 6379)
    assert hc._checks["redis"].kind == "tcp"


def test_add_db() -> None:
    hc = HealthCheck()
    hc.add_db("primary", "SELECT 1")
    assert hc._checks["primary"].kind == "db"


def test_add_redis() -> None:
    hc = HealthCheck()
    hc.add_redis("cache")
    assert hc._checks["cache"].kind == "redis"


def test_add_custom() -> None:
    async def my_check() -> tuple[CheckStatus, dict[str, Any]]:
        return CheckStatus.OK, {"x": 1}

    hc = HealthCheck()
    hc.add_custom("custom", my_check)
    assert hc._checks["custom"].kind == "custom"


def test_add_with_depends_on() -> None:
    hc = HealthCheck()
    hc.add_http("a", "http://x").add_http("b", "http://y", depends_on=["a"])
    assert hc._checks["b"].depends_on == ["a"]


def test_add_with_critical_false() -> None:
    hc = HealthCheck()
    hc.add_http("soft", "http://x", critical=False)
    assert hc._checks["soft"].critical is False


def test_check_result_default_critical() -> None:
    cr = CheckResult(name="x", status=CheckStatus.OK, latency_ms=1.0)
    assert cr.critical is True
    assert cr.error is None
    assert cr.details == {}


def test_health_report_dataclass() -> None:
    r = HealthReport(
        overall=HealthStatus.HEALTHY,
        results={"a": CheckResult("a", CheckStatus.OK, 1.0)},
        timestamp=123.0,
    )
    assert r.overall is HealthStatus.HEALTHY
    assert r.timestamp == 123.0
    assert r.is_healthy is True
    assert r.failed == []
    assert r.degraded == []


# ---------------------------------------------------------------------------
# Run / parallel
# ---------------------------------------------------------------------------


async def test_run_all_healthy(
    tcp_pair: tuple[asyncio.AbstractServer, int],
    http_pair: tuple[asyncio.AbstractServer, int],
) -> None:
    _, tcp_port = tcp_pair
    _, http_port = http_pair
    hc = HealthCheck(cache_ttl=0.0)
    hc.add_tcp("redis", "127.0.0.1", tcp_port)
    hc.add_http("api", f"http://127.0.0.1:{http_port}/ping")
    hc.add_custom("always_ok", _ok_check)
    report = await hc.run()
    assert report.overall is HealthStatus.HEALTHY
    assert all(r.status is CheckStatus.OK for r in report.results.values())


async def test_run_one_check_fails(
    http_pair: tuple[asyncio.AbstractServer, int],
    http_500_pair: tuple[asyncio.AbstractServer, int],
) -> None:
    _, ok_port = http_pair
    _, bad_port = http_500_pair
    hc = HealthCheck(cache_ttl=0.0)
    hc.add_http("ok_url", f"http://127.0.0.1:{ok_port}/x")
    hc.add_http("bad_url", f"http://127.0.0.1:{bad_port}/never")
    hc.add_custom("ok2", _ok_check)
    report = await hc.run()
    statuses = {n: r.status for n, r in report.results.items()}
    assert statuses["ok_url"] is CheckStatus.OK
    assert statuses["bad_url"] is CheckStatus.FAILED
    assert statuses["ok2"] is CheckStatus.OK


async def test_run_parallel() -> None:
    """3 checks, каждый ~0.15s → общее время < 0.35s (а не > 0.45s sequential)."""

    async def slow() -> tuple[CheckStatus, dict[str, Any]]:
        await asyncio.sleep(0.15)
        return CheckStatus.OK, {}

    hc = HealthCheck(cache_ttl=0.0)
    for i in range(3):
        hc.add_custom(f"c{i}", slow)
    start = time.perf_counter()
    report = await hc.run()
    elapsed = time.perf_counter() - start
    assert report.overall is HealthStatus.HEALTHY
    assert elapsed < 0.35, f"checks didn't run in parallel ({elapsed:.3f}s)"


async def test_run_dependency_order() -> None:
    """B (depends_on A) запускается только после завершения A."""
    order: list[str] = []
    a_done = asyncio.Event()

    async def a() -> tuple[CheckStatus, dict[str, Any]]:
        order.append("a_start")
        await asyncio.sleep(0.05)
        a_done.set()
        order.append("a_end")
        return CheckStatus.OK, {}

    async def b() -> tuple[CheckStatus, dict[str, Any]]:
        await a_done.wait()  # гарантированно после a_end
        order.append("b")
        return CheckStatus.OK, {}

    hc = HealthCheck(cache_ttl=0.0)
    hc.add_custom("a", a)
    hc.add_custom("b", b, depends_on=["a"])
    await hc.run()
    assert order.index("a_end") < order.index("b")


async def test_run_circular_dependency_raises() -> None:
    """add_* не ловит self-dep, но валидация в run() ловит A→B→A."""
    hc = HealthCheck(cache_ttl=0.0)
    hc.add_custom("a", _ok_check, depends_on=["b"])
    hc.add_custom("b", _ok_check, depends_on=["a"])
    with pytest.raises(ValueError, match="circular"):
        await hc.run()


async def test_self_dependency_raises() -> None:
    hc = HealthCheck()
    with pytest.raises(ValueError, match="cannot depend on itself"):
        hc.add_http("loop", "http://x", depends_on=["loop"])


def test_dag_validation_missing_dep() -> None:
    hc = HealthCheck()
    hc.add_custom("a", _ok_check, depends_on=["ghost"])
    with pytest.raises(KeyError, match="unknown check 'ghost'"):
        asyncio.run(hc.run())


# ---------------------------------------------------------------------------
# Timeout
# ---------------------------------------------------------------------------


async def test_run_timeout() -> None:
    async def slow() -> tuple[CheckStatus, dict[str, Any]]:
        await asyncio.sleep(2.0)
        return CheckStatus.OK, {}

    hc = HealthCheck(default_timeout=0.1, cache_ttl=0.0)
    hc.add_custom("slow", slow)
    report = await hc.run()
    r = report.results["slow"]
    assert r.status is CheckStatus.FAILED
    assert r.error is not None
    assert "timeout" in r.error.lower()


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


async def test_run_cache_returns_cached_within_ttl() -> None:
    calls: list[int] = []

    async def fn() -> tuple[CheckStatus, dict[str, Any]]:
        calls.append(1)
        return CheckStatus.OK, {"n": len(calls)}

    hc = HealthCheck(cache_ttl=10.0)
    hc.add_custom("c", fn)
    r1 = await hc.run_one("c")
    r2 = await hc.run_one("c")
    assert len(calls) == 1
    assert r1.details == r2.details


async def test_run_no_cache_after_ttl() -> None:
    calls: list[int] = []

    async def fn() -> tuple[CheckStatus, dict[str, Any]]:
        calls.append(1)
        return CheckStatus.OK, {}

    hc = HealthCheck(cache_ttl=0.05)
    hc.add_custom("c", fn)
    await hc.run_one("c")
    await asyncio.sleep(0.1)
    await hc.run_one("c")
    assert len(calls) == 2


def test_clear_cache() -> None:
    hc = HealthCheck()
    hc._cache["x"] = (CheckResult("x", CheckStatus.OK, 0.0), time.time())
    hc.clear_cache()
    assert hc._cache == {}


# ---------------------------------------------------------------------------
# Status logic
# ---------------------------------------------------------------------------


async def test_status_healthy() -> None:
    hc = HealthCheck(cache_ttl=0.0)
    hc.add_custom("a", _ok_check)
    hc.add_custom("b", _ok_check)
    report = await hc.run()
    assert report.overall is HealthStatus.HEALTHY


async def test_status_degraded_non_critical_fail() -> None:
    """Только non-critical check падает → DEGRADED."""

    async def fail() -> tuple[CheckStatus, dict[str, Any]]:
        return CheckStatus.FAILED, {"reason": "boom"}

    hc = HealthCheck(cache_ttl=0.0)
    hc.add_custom("soft", fail, critical=False)
    hc.add_custom("ok", _ok_check)
    report = await hc.run()
    assert report.overall is HealthStatus.DEGRADED


async def test_status_degraded_check_status() -> None:
    """Check возвращает DEGRADED → overall DEGRADED."""

    async def degraded() -> tuple[CheckStatus, dict[str, Any]]:
        return CheckStatus.DEGRADED, {}

    hc = HealthCheck(cache_ttl=0.0)
    hc.add_custom("a", degraded)
    report = await hc.run()
    assert report.overall is HealthStatus.DEGRADED


async def test_status_unhealthy_critical_fail() -> None:
    async def fail() -> tuple[CheckStatus, dict[str, Any]]:
        return CheckStatus.FAILED, {}

    hc = HealthCheck(cache_ttl=0.0)
    hc.add_custom("crit", fail, critical=True)
    report = await hc.run()
    assert report.overall is HealthStatus.UNHEALTHY


# ---------------------------------------------------------------------------
# Executors (DB/Redis)
# ---------------------------------------------------------------------------


async def test_db_check_uses_executor() -> None:
    called: list[str] = []

    async def executor(query: str) -> tuple[CheckStatus, dict[str, Any]]:
        called.append(query)
        return CheckStatus.OK, {"rows": 1}

    hc = HealthCheck(cache_ttl=0.0)
    hc.set_db_executor(executor)
    hc.add_db("primary", "SELECT 42")
    report = await hc.run()
    assert called == ["SELECT 42"]
    assert report.results["primary"].status is CheckStatus.OK


async def test_db_check_without_executor_fails() -> None:
    hc = HealthCheck(cache_ttl=0.0)
    hc.add_db("primary")
    report = await hc.run()
    r = report.results["primary"]
    assert r.status is CheckStatus.FAILED
    assert r.details.get("reason") == "no db_executor registered"


async def test_redis_check_uses_executor() -> None:
    called: list[int] = []

    async def executor() -> tuple[CheckStatus, dict[str, Any]]:
        called.append(1)
        return CheckStatus.OK, {"ping": "pong"}

    hc = HealthCheck(cache_ttl=0.0)
    hc.set_redis_executor(executor)
    hc.add_redis("cache")
    report = await hc.run()
    assert called == [1]
    assert report.results["cache"].details == {"ping": "pong"}


# ---------------------------------------------------------------------------
# Network (real local server) + exception handling
# ---------------------------------------------------------------------------


async def test_tcp_check_pass(tcp_pair: tuple[asyncio.AbstractServer, int]) -> None:
    _, port = tcp_pair
    hc = HealthCheck(cache_ttl=0.0)
    hc.add_tcp("svc", "127.0.0.1", port)
    r = await hc.run_one("svc")
    assert r.status is CheckStatus.OK
    assert r.details["port"] == port


async def test_tcp_check_fail_closed_port() -> None:
    closed = _free_port()  # bind-then-release → guaranteed closed
    hc = HealthCheck(default_timeout=0.5, cache_ttl=0.0)
    hc.add_tcp("svc", "127.0.0.1", closed)
    r = await hc.run_one("svc")
    assert r.status is CheckStatus.FAILED


async def test_http_check_pass(http_pair: tuple[asyncio.AbstractServer, int]) -> None:
    _, port = http_pair
    hc = HealthCheck(cache_ttl=0.0)
    hc.add_http("svc", f"http://127.0.0.1:{port}/")
    r = await hc.run_one("svc")
    assert r.status is CheckStatus.OK
    assert r.details["status_code"] == 200


async def test_http_check_fail_500(
    http_500_pair: tuple[asyncio.AbstractServer, int],
) -> None:
    _, port = http_500_pair
    hc = HealthCheck(cache_ttl=0.0)
    hc.add_http("svc", f"http://127.0.0.1:{port}/")
    r = await hc.run_one("svc")
    assert r.status is CheckStatus.FAILED
    assert r.details["status_code"] == 500


async def test_run_empty() -> None:
    hc = HealthCheck()
    report = await hc.run()
    assert report.overall is HealthStatus.HEALTHY
    assert report.results == {}


async def test_custom_check_exception_caught() -> None:
    async def boom() -> tuple[CheckStatus, dict[str, Any]]:
        raise RuntimeError("kaboom")

    hc = HealthCheck(cache_ttl=0.0)
    hc.add_custom("bad", boom, critical=False)
    report = await hc.run()
    r = report.results["bad"]
    assert r.status is CheckStatus.FAILED
    assert r.error is not None
    assert "RuntimeError" in r.error
    assert "kaboom" in r.error
    # non-critical fail → DEGRADED, не UNHEALTHY
    assert report.overall is HealthStatus.DEGRADED


async def test_run_one_unknown_raises() -> None:
    hc = HealthCheck()
    with pytest.raises(KeyError, match="unknown check"):
        await hc.run_one("nope")


# ---------------------------------------------------------------------------
# Helpers (функции)
# ---------------------------------------------------------------------------


async def _ok_check() -> tuple[CheckStatus, dict[str, Any]]:
    return CheckStatus.OK, {}
