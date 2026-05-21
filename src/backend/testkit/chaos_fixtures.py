"""ADR-0055 — toxiproxy fault-injection helpers + pytest fixtures.

Использование::

    import pytest
    from src.backend.testkit.chaos_fixtures import (
        toxiproxy_client,
        with_latency,
        with_timeout,
    )

    @pytest.mark.chaos
    @pytest.mark.requires_toxiproxy
    async def test_breaker_opens_under_latency(toxiproxy_client):
        proxy = toxiproxy_client.proxies.get("postgres")
        with with_latency(proxy, ms=5000):
            # ваш код вызова через proxy
            ...

Toxiproxy запускается в docker-compose.dev.yml на порту 8474.
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # toxiproxy-python типы; runtime-импорт через lazy-load,
    # чтобы chaos-тесты могли skip-аться без установки SDK.
    pass

__all__ = (
    "TOXIPROXY_URL",
    "connection_killer",
    "toxiproxy_available",
    "with_bandwidth",
    "with_latency",
    "with_slow_close",
    "with_timeout",
)


TOXIPROXY_URL = os.environ.get("TOXIPROXY_URL", "http://localhost:8474")
"""URL toxiproxy-сервера; берётся из env или дефолт localhost:8474."""


def toxiproxy_available() -> bool:
    """Проверить, доступен ли toxiproxy-сервер.

    Тесты должны skip-аться (``pytest.skip``) если ``False``.
    """
    try:
        import httpx

        response = httpx.get(f"{TOXIPROXY_URL}/version", timeout=1.0)
        return response.status_code == 200
    except Exception:
        return False


@contextlib.contextmanager
def with_latency(proxy: Any, ms: int, jitter: int = 0) -> Iterator[None]:
    """Добавить latency-toxic на proxy.

    Args:
        proxy: ``toxiproxy.Proxy`` instance.
        ms: Базовая задержка в миллисекундах.
        jitter: Джиттер в миллисекундах (random uniform 0..jitter).
    """
    toxic = proxy.add_toxic(
        name=f"latency_{ms}",
        type="latency",
        attributes={"latency": ms, "jitter": jitter},
    )
    try:
        yield
    finally:
        with contextlib.suppress(Exception):
            proxy.destroy_toxic(toxic.name)


@contextlib.contextmanager
def with_timeout(proxy: Any, ms: int) -> Iterator[None]:
    """Добавить timeout-toxic — обрывает соединение через ms ms.

    Args:
        proxy: ``toxiproxy.Proxy`` instance.
        ms: Время до обрыва в миллисекундах.
    """
    toxic = proxy.add_toxic(
        name=f"timeout_{ms}", type="timeout", attributes={"timeout": ms}
    )
    try:
        yield
    finally:
        with contextlib.suppress(Exception):
            proxy.destroy_toxic(toxic.name)


@contextlib.contextmanager
def with_bandwidth(proxy: Any, kbps: int) -> Iterator[None]:
    """Лимитировать пропускную способность.

    Args:
        proxy: ``toxiproxy.Proxy`` instance.
        kbps: Лимит в килобитах в секунду.
    """
    toxic = proxy.add_toxic(
        name=f"bandwidth_{kbps}", type="bandwidth", attributes={"rate": kbps}
    )
    try:
        yield
    finally:
        with contextlib.suppress(Exception):
            proxy.destroy_toxic(toxic.name)


@contextlib.contextmanager
def with_slow_close(proxy: Any, delay_ms: int) -> Iterator[None]:
    """Добавить slow_close-toxic — задерживает TCP FIN.

    Args:
        proxy: ``toxiproxy.Proxy`` instance.
        delay_ms: Задержка перед закрытием в миллисекундах.
    """
    toxic = proxy.add_toxic(
        name=f"slow_close_{delay_ms}", type="slow_close", attributes={"delay": delay_ms}
    )
    try:
        yield
    finally:
        with contextlib.suppress(Exception):
            proxy.destroy_toxic(toxic.name)


@contextlib.contextmanager
def connection_killer(proxy: Any) -> Iterator[None]:
    """Резко обрывает все активные соединения на proxy.

    Используется для симуляции network partition / process kill.
    """
    proxy.disable()
    try:
        yield
    finally:
        with contextlib.suppress(Exception):
            proxy.enable()
