"""Desktop RPA session pool (Sprint 21 W6, F-12 + B-09 closure).

Источник: PLAN.md V22.2 §4 + B-09 closure (Desktop RPA создаёт новый
Application() каждый запрос — массивный overhead).

Назначение:
    Пул persistent ``httpx.AsyncClient``-инстансов с session affinity по
    ``app_name`` — каждое целевое приложение получает свой long-lived client
    (keep-alive, connection pool). Auto-reconnect на stale handle (HTTP 410
    / connection refused). TTL для idle sessions — 30 минут (по умолчанию).

Структура pool:
    * ``_sessions: dict[str, _PooledSession]`` — by app_name.
    * ``acquire(app_name)`` — async context manager, лизит handle.
    * ``shutdown()`` — graceful close всех клиентов.

Архитектура:
    Используется как DI-инжекция в :class:`DesktopRpaClient` (S21 W6 carryover —
    рефактор client'а на pool-aware режим). По умолчанию pool не активен;
    feature-flag ``desktop_rpa_session_pool_enabled`` (W0) включает интеграцию.

См. также:
    * :class:`src.backend.services.rpa.desktop_rpa_client.DesktopRpaClient`
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import httpx

__all__ = (
    "DesktopRPASessionPool",
    "DesktopRPASessionStats",
    "get_desktop_rpa_pool",
    "set_desktop_rpa_pool",
)

_logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _PooledSession:
    """Внутреннее состояние одного pooled-клиента."""

    app_name: str
    client: httpx.AsyncClient
    created_at: float
    last_used_at: float = 0.0
    in_use: bool = False
    reconnect_count: int = 0


@dataclass(slots=True, frozen=True)
class DesktopRPASessionStats:
    """Снимок состояния pool (для admin/observability)."""

    total: int
    in_use: int
    idle: int
    by_app: dict[str, dict[str, Any]] = field(default_factory=dict)


class DesktopRPASessionPool:
    """Persistent httpx.AsyncClient pool с session affinity по app_name.

    Args:
        base_url: URL windows-worker sidecar (общий для всех app_name).
        api_key: опц. API-key (заголовок X-API-Key).
        timeout: connect+read timeout (default 30s).
        ttl_seconds: idle TTL до закрытия (default 1800s = 30min).
        max_sessions: верхний лимит pool (default 16).
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None = None,
        timeout: float = 30.0,
        ttl_seconds: float = 1800.0,
        max_sessions: int = 16,
    ) -> None:
        if not base_url:
            raise ValueError("base_url обязателен")
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout
        self._ttl = ttl_seconds
        self._max_sessions = max_sessions
        self._sessions: dict[str, _PooledSession] = {}
        self._lock = asyncio.Lock()

    def _make_client(self) -> httpx.AsyncClient:
        """Создаёт новый AsyncClient с keep-alive + headers."""
        headers: dict[str, str] = {}
        if self._api_key:
            headers["X-API-Key"] = self._api_key
        return httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(self._timeout),
            headers=headers,
            limits=httpx.Limits(max_keepalive_connections=4, max_connections=8),
        )

    async def _get_or_create(self, app_name: str) -> _PooledSession:
        """Возвращает session по app_name; создаёт при отсутствии."""
        session = self._sessions.get(app_name)
        now = time.monotonic()
        if session is not None:
            # Stale TTL check
            if not session.in_use and (now - session.last_used_at) > self._ttl:
                _logger.info(
                    "desktop_rpa_pool: TTL expired для %s — recreate", app_name
                )
                try:
                    await session.client.aclose()
                except Exception:  # noqa: BLE001
                    pass
                session = None
        if session is None:
            if len(self._sessions) >= self._max_sessions:
                # Простая eviction policy: убрать самую старую idle session
                oldest_app, oldest = min(
                    (
                        (a, s)
                        for a, s in self._sessions.items()
                        if not s.in_use
                    ),
                    key=lambda kv: kv[1].last_used_at,
                    default=(None, None),
                )
                if oldest_app is not None and oldest is not None:
                    try:
                        await oldest.client.aclose()
                    except Exception:  # noqa: BLE001
                        pass
                    self._sessions.pop(oldest_app, None)
            session = _PooledSession(
                app_name=app_name,
                client=self._make_client(),
                created_at=now,
                last_used_at=now,
            )
            self._sessions[app_name] = session
        return session

    @asynccontextmanager
    async def acquire(self, app_name: str) -> AsyncIterator[httpx.AsyncClient]:
        """Лизит httpx-client для ``app_name`` (session affinity).

        Использование::

            async with pool.acquire("notepad") as client:
                response = await client.post("/rpa/click", json={...})
        """
        async with self._lock:
            session = await self._get_or_create(app_name)
            session.in_use = True
        try:
            yield session.client
        except (httpx.ConnectError, httpx.RemoteProtocolError) as exc:
            # Stale handle — закрыть и пометить для reconnect на следующий acquire
            _logger.warning(
                "desktop_rpa_pool: stale connection для %s — reconnect (%s)",
                app_name,
                exc,
            )
            try:
                await session.client.aclose()
            except Exception:  # noqa: BLE001
                pass
            async with self._lock:
                self._sessions.pop(app_name, None)
            raise
        finally:
            async with self._lock:
                if app_name in self._sessions:
                    self._sessions[app_name].in_use = False
                    self._sessions[app_name].last_used_at = time.monotonic()

    async def reconnect(self, app_name: str) -> None:
        """Принудительный recreate session по app_name."""
        async with self._lock:
            session = self._sessions.pop(app_name, None)
        if session is not None:
            try:
                await session.client.aclose()
            except Exception:  # noqa: BLE001
                pass

    async def stats(self) -> DesktopRPASessionStats:
        """Снимок состояния pool."""
        async with self._lock:
            total = len(self._sessions)
            in_use = sum(1 for s in self._sessions.values() if s.in_use)
            idle = total - in_use
            by_app = {
                name: {
                    "in_use": s.in_use,
                    "reconnect_count": s.reconnect_count,
                    "age_seconds": time.monotonic() - s.created_at,
                    "idle_seconds": (
                        time.monotonic() - s.last_used_at if not s.in_use else 0.0
                    ),
                }
                for name, s in self._sessions.items()
            }
        return DesktopRPASessionStats(
            total=total, in_use=in_use, idle=idle, by_app=by_app
        )

    async def shutdown(self) -> None:
        """Закрывает все session-clients."""
        async with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for s in sessions:
            try:
                await s.client.aclose()
            except Exception:  # noqa: BLE001
                _logger.debug("desktop_rpa_pool: error closing %s", s.app_name)


# Module-level singleton
_default_pool: DesktopRPASessionPool | None = None


def get_desktop_rpa_pool() -> DesktopRPASessionPool | None:
    """Возвращает дефолтный pool (или None)."""
    return _default_pool


def set_desktop_rpa_pool(pool: DesktopRPASessionPool | None) -> None:
    """Устанавливает дефолтный pool (вызывается в lifespan)."""
    global _default_pool
    _default_pool = pool
