"""S40 W3 — HealthCheck с dependency graph.

Dependency-graph health checker для ``/health`` endpoint. Поддерживает
HTTP/TCP/DB/Redis/custom checks, параллельное выполнение, per-check timeout,
DAG-валидацию, кэширование и статусы healthy/degraded/unhealthy.

Stdlib-only (``asyncio``, ``dataclasses``, ``time``, ``enum``, ``urllib``).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from urllib.parse import urlparse

__all__ = ("CheckStatus", "HealthStatus", "CheckResult", "HealthReport", "HealthCheck")


class CheckStatus(str, Enum):
    """Per-check статус: OK / DEGRADED / FAILED.

    Используется :class:`CheckResult` для маркировки результата
    каждого индивидуального health-check. ``HealthStatus`` (overall)
    агрегирует несколько ``CheckStatus`` в один общий статус системы.
    """

    OK = "ok"
    DEGRADED = "degraded"
    FAILED = "failed"


class HealthStatus(str, Enum):
    """Overall system health: HEALTHY / DEGRADED / UNHEALTHY.

    Агрегированный статус системы: HEALTHY = все critical checks OK,
    DEGRADED = есть DEGRADED checks или non-critical FAILED,
    UNHEALTHY = хотя бы один critical check FAILED.
    """

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass
class CheckResult:
    """Результат одного health-check.

    Attributes:
        name: Имя check (из :meth:`HealthCheck.add_*`).
        status: ``CheckStatus`` (OK / DEGRADED / FAILED).
        latency_ms: Время выполнения (мс).
        error: Текст ошибки при FAILED, иначе None.
        details: Доп. метаданные (e.g. ``{"rows": 42}`` для DB query).
        critical: True если failure приводит к UNHEALTHY overall.
    """

    name: str
    status: CheckStatus
    latency_ms: float
    error: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    critical: bool = True


@dataclass
class HealthReport:
    """Агрегированный health report после :meth:`HealthCheck.run`.

    Attributes:
        overall: Агрегированный :class:`HealthStatus`.
        results: dict name → :class:`CheckResult` для всех выполненных checks.
        timestamp: Unix timestamp момента формирования отчёта.
    """

    overall: HealthStatus
    results: dict[str, CheckResult]
    timestamp: float

    @property
    def is_healthy(self) -> bool:
        """True если ``overall`` == ``HealthStatus.HEALTHY`` (все OK)."""
        return self.overall is HealthStatus.HEALTHY

    @property
    def failed(self) -> list[str]:
        """Список имён checks со статусом ``CheckStatus.FAILED``."""
        return [n for n, r in self.results.items() if r.status is CheckStatus.FAILED]

    @property
    def degraded(self) -> list[str]:
        """Список имён checks со статусом ``CheckStatus.DEGRADED``."""
        return [n for n, r in self.results.items() if r.status is CheckStatus.DEGRADED]


CheckFn = Callable[[], Awaitable[tuple[CheckStatus, dict[str, Any]]]]
DbExecutor = Callable[[str], Awaitable[tuple[CheckStatus, dict[str, Any]]]]
RedisExecutor = Callable[[], Awaitable[tuple[CheckStatus, dict[str, Any]]]]


@dataclass
class _CheckDef:
    name: str
    kind: str
    timeout: float
    critical: bool
    depends_on: list[str]
    run: CheckFn


class HealthCheck:
    """Dependency-graph health checker.

    Args:
        default_timeout: Таймаут на check (сек), если не задан явно.
        cache_ttl: TTL кэша результатов (сек).
    """

    def __init__(
        self, *, default_timeout: float = 5.0, cache_ttl: float = 30.0
    ) -> None:
        self._default_timeout = float(default_timeout)
        self._cache_ttl = float(cache_ttl)
        self._checks: dict[str, _CheckDef] = {}
        self._cache: dict[str, tuple[CheckResult, float]] = {}
        self._db_executor: DbExecutor | None = None
        self._redis_executor: RedisExecutor | None = None

    # -- executors --------------------------------------------------------

    def set_db_executor(self, executor: DbExecutor) -> None:
        """Зарегистрировать async-callable(query) -> (status, details)."""
        self._db_executor = executor
        self._invalidate_cache()

    def set_redis_executor(self, executor: RedisExecutor) -> None:
        """Зарегистрировать async-callable() -> (status, details)."""
        self._redis_executor = executor
        self._invalidate_cache()

    # -- registration -----------------------------------------------------

    def add_http(
        self,
        name: str,
        url: str,
        *,
        timeout: float | None = None,
        depends_on: list[str] | None = None,
        critical: bool = True,
    ) -> HealthCheck:
        """Добавить HTTP check: ``HEAD/GET url`` через aiohttp."""

        async def _run() -> tuple[CheckStatus, dict[str, Any]]:
            return await self._http_check(url)

        return self._add(name, "http", timeout, critical, depends_on, _run)

    def add_tcp(
        self,
        name: str,
        host: str,
        port: int,
        *,
        timeout: float | None = None,
        depends_on: list[str] | None = None,
        critical: bool = True,
    ) -> HealthCheck:
        """Добавить TCP check: ``connect(host, port)`` через asyncio.open_connection."""

        async def _run() -> tuple[CheckStatus, dict[str, Any]]:
            return await self._tcp_check(host, port)

        return self._add(name, "tcp", timeout, critical, depends_on, _run)

    def add_db(
        self,
        name: str,
        query: str = "SELECT 1",
        *,
        timeout: float | None = None,
        depends_on: list[str] | None = None,
        critical: bool = True,
    ) -> HealthCheck:
        """Добавить DB check: выполнить ``query`` через registered ``db_executor``.

        Требует :meth:`set_db_executor` до :meth:`run`; иначе FAILED
        с ``{"reason": "no db_executor registered"}``.
        """

        async def _run() -> tuple[CheckStatus, dict[str, Any]]:
            if self._db_executor is None:
                return CheckStatus.FAILED, {"reason": "no db_executor registered"}
            return await self._db_executor(query)

        return self._add(name, "db", timeout, critical, depends_on, _run)

    def add_redis(
        self,
        name: str,
        *,
        timeout: float | None = None,
        depends_on: list[str] | None = None,
        critical: bool = True,
    ) -> HealthCheck:
        """Добавить Redis check: ``PING`` через registered ``redis_executor``.

        Требует :meth:`set_redis_executor` до :meth:`run`; иначе FAILED
        с ``{"reason": "no redis_executor registered"}``.
        """

        async def _run() -> tuple[CheckStatus, dict[str, Any]]:
            if self._redis_executor is None:
                return CheckStatus.FAILED, {"reason": "no redis_executor registered"}
            return await self._redis_executor()

        return self._add(name, "redis", timeout, critical, depends_on, _run)

    def add_custom(
        self,
        name: str,
        check_fn: CheckFn,
        *,
        timeout: float | None = None,
        depends_on: list[str] | None = None,
        critical: bool = True,
    ) -> HealthCheck:
        """Добавить custom check: вызвать user-provided ``check_fn()``.

        ``check_fn`` — async callable возвращает ``(status, details)``.
        """
        return self._add(name, "custom", timeout, critical, depends_on, check_fn)

    # -- run --------------------------------------------------------------

    async def run(self) -> HealthReport:
        """Запустить все checks в topological order с кэшированием.

        Возвращает :class:`HealthReport` с агрегированным overall.
        Если DAG содержит цикл — :class:`ValueError`.
        """
        self._validate_dag()
        if not self._checks:
            return HealthReport(
                overall=HealthStatus.HEALTHY, results={}, timestamp=time.time()
            )
        all_results: dict[str, CheckResult] = {}
        for layer in self._topological_layers():
            results = await asyncio.gather(*(self._run_with_cache(n) for n in layer))
            for n, r in zip(layer, results, strict=True):
                all_results[n] = r
        return HealthReport(
            overall=self._aggregate(all_results),
            results=all_results,
            timestamp=time.time(),
        )

    async def run_one(self, name: str) -> CheckResult:
        """Запустить один check по имени (с кэшированием).

        Args:
            name: Имя check (из :meth:`add_*`).

        Returns:
            :class:`CheckResult`.

        Raises:
            KeyError: ``name`` не зарегистрирован.
        """
        if name not in self._checks:
            raise KeyError(f"unknown check: {name!r}")
        return await self._run_with_cache(name)

    def clear_cache(self) -> None:
        """Очистить кэш результатов checks (force re-run)."""
        self._cache.clear()

    # -- internals --------------------------------------------------------

    def _add(
        self,
        name: str,
        kind: str,
        timeout: float | None,
        critical: bool,
        depends_on: list[str] | None,
        run: CheckFn,
    ) -> HealthCheck:
        deps = list(depends_on) if depends_on else []
        if name in deps:
            raise ValueError(f"check {name!r} cannot depend on itself")
        self._checks[name] = _CheckDef(
            name=name,
            kind=kind,
            timeout=float(timeout) if timeout is not None else self._default_timeout,
            critical=critical,
            depends_on=deps,
            run=run,
        )
        self._invalidate_cache()
        return self

    def _invalidate_cache(self) -> None:
        self._cache.clear()

    def _validate_dag(self) -> None:
        for name, chk in self._checks.items():
            for dep in chk.depends_on:
                if dep == name:
                    raise ValueError(f"check {name!r} depends on itself")
                if dep not in self._checks:
                    raise KeyError(f"check {name!r} depends on unknown check {dep!r}")
        WHITE, GRAY, BLACK = 0, 1, 2
        color: dict[str, int] = {n: WHITE for n in self._checks}

        def visit(node: str) -> None:
            if color[node] == GRAY:
                raise ValueError(f"circular dependency detected at {node!r}")
            if color[node] == BLACK:
                return
            color[node] = GRAY
            for dep in self._checks[node].depends_on:
                visit(dep)
            color[node] = BLACK

        for n in self._checks:
            if color[n] == WHITE:
                visit(n)

    def _topological_layers(self) -> list[list[str]]:
        in_deg: dict[str, int] = {n: len(c.depends_on) for n, c in self._checks.items()}
        children: dict[str, list[str]] = {n: [] for n in self._checks}
        for n, c in self._checks.items():
            for dep in c.depends_on:
                children[dep].append(n)
        layers: list[list[str]] = []
        ready = sorted(n for n, d in in_deg.items() if d == 0)
        processed = 0
        while ready:
            layers.append(ready)
            processed += len(ready)
            next_ready: list[str] = []
            for n in ready:
                for child in children[n]:
                    in_deg[child] -= 1
                    if in_deg[child] == 0:
                        next_ready.append(child)
            ready = sorted(next_ready)
        if processed != len(self._checks):
            raise ValueError("circular dependency detected")
        return layers

    async def _run_with_cache(self, name: str) -> CheckResult:
        now = time.time()
        cached = self._cache.get(name)
        if cached is not None and (now - cached[1]) < self._cache_ttl:
            return cached[0]
        result = await self._execute(name)
        self._cache[name] = (result, now)
        return result

    async def _execute(self, name: str) -> CheckResult:
        chk = self._checks[name]
        start = time.perf_counter()
        try:
            status, details = await asyncio.wait_for(chk.run(), timeout=chk.timeout)
        except asyncio.TimeoutError:
            return CheckResult(
                name=name,
                status=CheckStatus.FAILED,
                latency_ms=(time.perf_counter() - start) * 1000.0,
                error=f"timeout after {chk.timeout}s",
                details={},
                critical=chk.critical,
            )
        except Exception as exc:  # noqa: BLE001 — health-checks fail-safe
            return CheckResult(
                name=name,
                status=CheckStatus.FAILED,
                latency_ms=(time.perf_counter() - start) * 1000.0,
                error=f"{type(exc).__name__}: {exc}",
                details={},
                critical=chk.critical,
            )
        if not isinstance(status, CheckStatus):
            status = CheckStatus.FAILED
        return CheckResult(
            name=name,
            status=status,
            latency_ms=(time.perf_counter() - start) * 1000.0,
            error=None,
            details=details,
            critical=chk.critical,
        )

    @staticmethod
    def _aggregate(results: dict[str, CheckResult]) -> HealthStatus:
        if not results:
            return HealthStatus.HEALTHY
        has_critical_fail = any(
            r.status is CheckStatus.FAILED and r.critical for r in results.values()
        )
        if has_critical_fail:
            return HealthStatus.UNHEALTHY
        has_any_fail = any(r.status is CheckStatus.FAILED for r in results.values())
        has_any_degraded = any(
            r.status in (CheckStatus.FAILED, CheckStatus.DEGRADED)
            for r in results.values()
        )
        if has_any_fail or has_any_degraded:
            return HealthStatus.DEGRADED
        return HealthStatus.HEALTHY

    # -- network checks (stdlib-only) -------------------------------------

    @staticmethod
    async def _http_check(url: str) -> tuple[CheckStatus, dict[str, Any]]:
        parsed = urlparse(url)
        scheme = (parsed.scheme or "http").lower()
        if scheme not in ("http", "https"):
            return CheckStatus.FAILED, {"reason": f"unsupported scheme {scheme!r}"}
        host = parsed.hostname
        if not host:
            return CheckStatus.FAILED, {"reason": "no host in url"}
        port = parsed.port or (443 if scheme == "https" else 80)
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        reader, writer = await asyncio.open_connection(
            host, port, ssl=scheme == "https"
        )
        try:
            writer.write(
                f"GET {path} HTTP/1.0\r\nHost: {host}\r\n"
                f"User-Agent: gd-healthcheck/1.0\r\nConnection: close\r\n\r\n".encode(
                    "ascii"
                )
            )
            await writer.drain()
            status_line = await asyncio.wait_for(reader.readline(), timeout=5.0)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:  # noqa: BLE001
                pass
        text = status_line.decode("latin-1", "replace").strip()
        parts = text.split(" ", 2)
        if len(parts) < 2 or not parts[1].isdigit():
            return CheckStatus.FAILED, {"reason": f"bad status line: {text!r}"}
        code = int(parts[1])
        if 200 <= code < 400:
            return CheckStatus.OK, {"status_code": code, "host": host, "port": port}
        return CheckStatus.FAILED, {"status_code": code, "host": host, "port": port}

    @staticmethod
    async def _tcp_check(host: str, port: int) -> tuple[CheckStatus, dict[str, Any]]:
        reader, writer = await asyncio.open_connection(host, port)
        del reader
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:  # noqa: BLE001
            pass
        return CheckStatus.OK, {"host": host, "port": port}



# S168 W11 P2-8: DEPRECATED — per docs/DEAD_CODE_AUDIT.md:139, файл
# помечен как мёртвый код. Per master prompt v8 P2-8: "Delete
# src/backend/ops/health.py or migrate into services/ops/health.py
# (also dead per DEAD_CODE_AUDIT)".
#
# Per Ponytail minimum, current commit does NOT delete the file:
# - tests/unit/ops/test_health.py (529 LOC) imports from here
# - 0 production callers
# - actual deletion requires deleting both files + verifying no
#   external consumers (separate WIP)
#
# WARNING: New code should use services/ops/health.py (canonical)
# или EntryPoints HealthEndpoint. Existing imports continue to work
# но emit deprecation warning.
import warnings
warnings.warn(
    "src.backend.ops.health is deprecated (S168 W11 P2-8), "
    "use src.backend.services.ops.health instead. Will be removed в S169+.",
    DeprecationWarning,
    stacklevel=2,
)
