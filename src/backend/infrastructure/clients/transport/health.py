"""Health facade для transport-клиентов (Milestone 1).

Агрегирует health-check всех transport-клиентов
``infrastructure/clients/transport/`` под единым интерфейсом.

Каждый connector обязан экспортировать ``is_healthy() -> bool`` (async)
или class ``Client``/``Pool`` (sync fallback).

Использование::

    from src.backend.infrastructure.clients.transport.health import (
        check_all_transport,
        get_transport_health,
    )

    # Полный отчёт
    report = await check_all_transport(timeout=2.0)
    # {"http": True, "smtp": False, ...}

    # Только один connector
    ok = await get_transport_health("http")

Pattern: ``clients/transport/*`` — все sync IO → обёртка через
``asyncio.to_thread``.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect

__all__ = ("check_all_transport", "get_transport_health", "HEALTH_CHECK_TIMEOUT")

#: Default timeout для каждого connector health probe.
HEALTH_CHECK_TIMEOUT: float = 2.0

#: Connectors, для которых определена функция ``is_healthy()``.
#: Пополняется автоматически при добавлении нового connector-модуля.
_TRACKED_CONNECTORS: tuple[str, ...] = (
    "http",
    "smtp",
    "sftp",
    "ftp",
    "imap",
    "nats",
    "grpc",
    "soap",
    "browser",
)


async def get_transport_health(name: str, *, timeout: float = HEALTH_CHECK_TIMEOUT) -> bool:
    """Проверить здоровье конкретного connector.

    Args:
        name: Имя connector (``http``, ``smtp``, ``sftp``, ...).
        timeout: Максимальное время проверки (сек).

    Returns:
        ``True`` если connector healthy, ``False`` иначе.
        Никогда не raises — все ошибки конвертируются в ``False``.
    """
    if name not in _TRACKED_CONNECTORS:
        return False
    try:
        module = importlib.import_module(
            f"src.backend.infrastructure.clients.transport.{name}"
        )
        check_fn = getattr(module, "is_healthy", None)
        if check_fn is None:
            return hasattr(module, "Client") or hasattr(module, "Pool")

        if inspect.iscoroutinefunction(check_fn):
            return bool(await asyncio.wait_for(check_fn(), timeout=timeout))
        return bool(await asyncio.to_thread(check_fn))
    except (ImportError, AttributeError, asyncio.TimeoutError, OSError):
        return False
    except Exception:
        return False


async def check_all_transport(
    *, timeout: float = HEALTH_CHECK_TIMEOUT, concurrent: bool = True
) -> dict[str, bool]:
    """Полный health-check всех transport connectors.

    Args:
        timeout: Per-connector timeout (sec).
        concurrent: Если True — все проверки параллельно (быстрее).

    Returns:
        ``{connector_name: is_healthy}`` для всех tracked connectors.
    """
    if concurrent:
        tasks = {
            name: asyncio.create_task(get_transport_health(name, timeout=timeout))
            for name in _TRACKED_CONNECTORS
        }
        results = await asyncio.gather(*tasks.values(), return_exceptions=False)
        return dict(zip(tasks.keys(), results, strict=False))
    return {
        name: await get_transport_health(name, timeout=timeout)
        for name in _TRACKED_CONNECTORS
    }
