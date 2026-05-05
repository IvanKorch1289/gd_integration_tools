"""IMAP connection pool (IL2.5).

До этой фазы `src/entrypoints/email/imap_monitor.py` открывал новое
соединение при каждом цикле poll — неэффективно, нагружает TCP-state на
IMAP-сервере (много CONNECT → LOGIN → LOGOUT), стрессует TLS handshake.

Решение — Queue-based pool по образцу SMTP (`src/infrastructure/clients/
transport/smtp.py`): keep N аутентифицированных соединений в asyncio.Queue,
acquire при запросе, release при окончании work-unit.

Интеграция: клиент `ImapConnectionPool` наследует `InfrastructureClient`,
регистрируется в `ConnectorRegistry` → участвует в единой lifecycle +
health + reload + metrics (IL1 foundation).

Коммерческий референс: MuleSoft Email Connector pooling, Apache Camel
`mail://` connection pool.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, AsyncIterator

if TYPE_CHECKING:
    from aioimaplib import IMAP4_SSL

from src.core.config.pooling import DEFAULT_POOLING_PROFILE, PoolingProfile
from src.infrastructure.clients.base_connector import HealthResult, InfrastructureClient
from src.infrastructure.observability.client_metrics import ClientMetricsMixin

_logger = logging.getLogger(__name__)


class ImapConnectionPool(ClientMetricsMixin, InfrastructureClient):
    """Pool IMAP-соединений для мониторинг-циклов.

    Конфиг:
      * `host` / `port` / `use_ssl` / `timeout` — стандартные.
      * `username` — логин.
      * `password_provider` — callable, возвращающий пароль (обычно из Vault).
        Позволяет ротацию: при ReconnectN-цикле провайдер вернёт свежий.
      * `pooling.max_size` — размер пула (N параллельных коннектов).

    API:
      * `async with pool.acquire() as imap: ...` — получить connection.
      * `async start() / stop()` — lifecycle (ConnectorRegistry-совместим).
      * `async health(mode)` — fast=count_idle; deep=NOOP на одной
        connection.
    """

    def __init__(
        self,
        *,
        name: str = "imap",
        host: str,
        port: int = 993,
        username: str,
        password_provider: Any,
        use_ssl: bool = True,
        timeout_s: float = 30.0,
        pooling: PoolingProfile | None = None,
    ) -> None:
        super().__init__(name=name, pooling=pooling or DEFAULT_POOLING_PROFILE)
        self._host = host
        self._port = port
        self._username = username
        self._password_provider = password_provider
        self._use_ssl = use_ssl
        self._timeout_s = timeout_s
        self._pool: asyncio.Queue["IMAP4_SSL"] = asyncio.Queue(
            maxsize=self.pooling.max_size
        )
        self._created: int = 0  # сколько соединений фактически открыто
        self._lock = asyncio.Lock()  # guard _created в multi-acquire

    async def start(self) -> None:
        if self._started:
            return
        # Pre-warm min_size соединений.
        for _ in range(self.pooling.min_size):
            conn = await self._dial()
            await self._pool.put(conn)
            self._created += 1
        self._started = True
        _logger.info(
            "imap pool started",
            extra={
                "name": self.name,
                "host": self._host,
                "min_size": self.pooling.min_size,
                "max_size": self.pooling.max_size,
            },
        )

    async def stop(self) -> None:
        if not self._started:
            return
        # Drain queue; logout каждое соединение.
        while not self._pool.empty():
            try:
                conn = self._pool.get_nowait()
            except asyncio.QueueEmpty:
                break
            with _suppress():
                await conn.logout()
        self._created = 0
        self._started = False
        _logger.info("imap pool stopped", extra={"name": self.name})

    async def health(self, mode: str = "fast") -> HealthResult:
        if not self._started:
            return HealthResult.failed(error="pool not started", mode=mode)  # type: ignore[arg-type]

        import time

        start = time.perf_counter()
        if mode == "fast":
            # Быстрая проверка: сколько free в queue + сколько создано.
            latency_ms = (time.perf_counter() - start) * 1000.0
            return HealthResult.ok(
                latency_ms=latency_ms,
                mode=mode,  # type: ignore[arg-type]
                pool_free=self._pool.qsize(),
                pool_created=self._created,
            )
        # Deep — acquire + NOOP.
        try:
            async with self.acquire() as imap:
                await asyncio.wait_for(imap.noop(), timeout=2.0)
            latency_ms = (time.perf_counter() - start) * 1000.0
            return HealthResult.ok(
                latency_ms=latency_ms,
                mode=mode,  # type: ignore[arg-type]
                probe="NOOP",
                pool_created=self._created,
            )
        except Exception as exc:  # noqa: BLE001
            return HealthResult.failed(
                error=f"{type(exc).__name__}: {exc}",
                mode=mode,  # type: ignore[arg-type]
                latency_ms=(time.perf_counter() - start) * 1000.0,
            )

    # -- Pool API -----------------------------------------------------

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator["IMAP4_SSL"]:
        """Получить IMAP-соединение из пула. По выходу — вернуть.

        Если очередь пустая и max_size не достигнут — открывается новое.
        Если достигнут и нет free — ждать до `acquire_timeout_s`, потом
        `asyncio.TimeoutError`.
        """
        if not self._started:
            raise RuntimeError(f"ImapConnectionPool '{self.name}' not started")

        conn: "IMAP4_SSL | None" = None
        try:
            try:
                conn = self._pool.get_nowait()
            except asyncio.QueueEmpty:
                async with self._lock:
                    if self._created < self.pooling.max_size:
                        conn = await self._dial()
                        self._created += 1
                    else:
                        # Дожидаемся freed connection.
                        conn = await asyncio.wait_for(
                            self._pool.get(), timeout=self.pooling.acquire_timeout_s
                        )
            # Verify livenessо: если connection упал — replace.
            if not await self._is_alive(conn):
                with _suppress():
                    await conn.logout()
                conn = await self._dial()
            async with self.track("ACQUIRE"):
                yield conn
        finally:
            if conn is not None:
                # Возвращаем в пул. Если переполнено (shouldn't happen,
                # но защитимся) — logout.
                try:
                    self._pool.put_nowait(conn)
                except asyncio.QueueFull:
                    with _suppress():
                        await conn.logout()
                    self._created -= 1

    # -- Private ------------------------------------------------------

    async def _dial(self) -> "IMAP4_SSL":
        """Открыть новое IMAP-соединение + LOGIN.

        Используется в `start()` (pre-warm) и `acquire()` (if free-pool
        пуст и есть место).
        """
        import aioimaplib

        if self._use_ssl:
            conn = aioimaplib.IMAP4_SSL(
                host=self._host, port=self._port, timeout=self._timeout_s
            )
        else:
            conn = aioimaplib.IMAP4(
                host=self._host, port=self._port, timeout=self._timeout_s
            )  # type: ignore[assignment]
        await conn.wait_hello_from_server()
        password = await _maybe_async(self._password_provider)
        await conn.login(self._username, password)
        return conn

    async def _is_alive(self, conn: "IMAP4_SSL") -> bool:
        """Cheap liveness-probe: NOOP должен вернуть OK."""
        try:
            await asyncio.wait_for(conn.noop(), timeout=1.5)
            return True
        except Exception:  # noqa: BLE001
            return False


# -- Helpers ---------------------------------------------------------


class _suppress:
    """Внутренний context-manager, который глотает exceptions (для cleanup-путей)."""

    def __enter__(self) -> None:
        return None

    def __exit__(self, *exc: Any) -> bool:
        return True  # suppress


async def _maybe_async(callable_or_value: Any) -> Any:
    """Позволяет передавать password_provider и как callable (sync/async), и
    как готовую строку (для тестов).
    """
    if callable(callable_or_value):
        result = callable_or_value()
        if asyncio.iscoroutine(result):
            return await result
        return result
    return callable_or_value


__all__ = ("ImapConnectionPool",)
