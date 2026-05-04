"""Profile-based маршрутизация логов в активные :class:`LogSink`-ы.

Wave 2.5 (Roadmap V10): единая точка, через которую structlog отправляет
event_dict во все настроенные backend-sinks (console / disk / Graylog).

Состав:
    * :func:`build_sinks_for_profile` — фабрика sink-ов по
      :class:`AppProfileChoices` (dev_light / dev / staging / prod);
    * :class:`SinkRouter` — держит активный список sink-ов, имеет
      ``dispatch`` и ``aclose``;
    * :func:`route_to_sinks` — structlog-processor, пересылающий
      event_dict во все активные sinks параллельно через
      :func:`asyncio.gather`.

Поведение в sync-контексте: structlog вызывает processor синхронно, поэтому
передача event_dict в sinks делается через :func:`asyncio.run_coroutine_threadsafe`
к фоновому event loop, либо через ``asyncio.create_task``, если processor
вызван внутри уже работающего loop. Если loop недоступен — fan-out
делается синхронно через ``asyncio.run`` в воркер-потоке.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Iterable
from typing import Any

from src.core.config.profile import AppProfileChoices, get_active_profile
from src.core.interfaces.log_sink import LogSink
from src.infrastructure.logging.backends import (
    ConsoleJsonLogSink,
    DiskRotatingLogSink,
    GraylogGelfLogSink,
)

__all__ = (
    "SinkRouter",
    "RouterLike",
    "build_sinks_for_profile",
    "configure_router",
    "get_router",
    "is_router_configured",
    "reset_router",
    "route_to_sinks",
)


class RouterLike:
    """Минимальный protocol-like контракт router'а (sync + batching).

    Реализуют :class:`SinkRouter` и :class:`BatchingSinkRouter`. Введён,
    чтобы :func:`route_to_sinks` мог одинаково работать с обоими типами.
    """

    async def dispatch(self, record: dict[str, Any]) -> None:  # pragma: no cover
        """Разослать record по sink-ам (или поставить в очередь batch'а)."""
        raise NotImplementedError

    async def aclose(self) -> None:  # pragma: no cover
        """Корректно закрыть router и все sink-ы."""
        raise NotImplementedError


_INTERNAL_LOG = logging.getLogger("logging.router")


# ---------------------------------------------------------------------- factory
def build_sinks_for_profile(
    profile: AppProfileChoices | None = None,
    *,
    disk_path: str = "logs/app.jsonl",
    graylog_host: str = "graylog",
    graylog_port: int = 12201,
    graylog_protocol: str = "udp",
) -> list[LogSink]:
    """Построить список sink-ов согласно профилю запуска.

    Маппинг (W2.5 DoD):

    * ``dev_light`` → ``[ConsoleJsonLogSink]``;
    * ``dev`` → ``[ConsoleJsonLogSink, DiskRotatingLogSink]``;
    * ``staging`` / ``prod`` → ``[GraylogGelfLogSink, DiskRotatingLogSink]``.

    Аргументы:
        profile: явный профиль; если ``None`` — берётся
            :func:`~src.core.config.profile.get_active_profile`.
        disk_path: путь к файлу для disk-rotating sink.
        graylog_host/port/protocol: параметры Graylog input.
    """
    active = profile if profile is not None else get_active_profile()

    match active:
        case AppProfileChoices.dev_light:
            return [ConsoleJsonLogSink()]
        case AppProfileChoices.dev:
            return [ConsoleJsonLogSink(), DiskRotatingLogSink(path=disk_path)]
        case AppProfileChoices.staging | AppProfileChoices.prod:
            return [
                GraylogGelfLogSink(
                    host=graylog_host,
                    port=graylog_port,
                    protocol="tcp" if graylog_protocol == "tcp" else "udp",
                ),
                DiskRotatingLogSink(path=disk_path),
            ]
        case _:
            return [ConsoleJsonLogSink()]


# ---------------------------------------------------------------------- router
class SinkRouter:
    """Хранилище активных sink-ов + диспатчер event_dict.

    :class:`SinkRouter` сам не настраивает structlog; он лишь предоставляет
    :meth:`dispatch`, который structlog-processor вызывает на каждый
    лог-event. Параллельная отправка в sinks делается через
    :func:`asyncio.gather` с ``return_exceptions=True`` — отказ
    одного sink не должен ронять другие.
    """

    def __init__(self, sinks: Iterable[LogSink] | None = None) -> None:
        self._sinks: list[LogSink] = list(sinks or [])

    @property
    def sinks(self) -> tuple[LogSink, ...]:
        """Текущий список sink-ов (read-only snapshot)."""
        return tuple(self._sinks)

    def add(self, sink: LogSink) -> None:
        """Добавить sink в список активных."""
        self._sinks.append(sink)

    def replace(self, sinks: Iterable[LogSink]) -> None:
        """Полностью заменить набор sink-ов."""
        self._sinks = list(sinks)

    async def dispatch(self, record: dict[str, Any]) -> None:
        """Разослать ``record`` во все sink-ы параллельно.

        Только healthy sink-и получают запись; нездоровые пропускаются,
        чтобы router быстро смог переключиться на fallback (например,
        с Graylog на disk при downtime).
        """
        targets = [s for s in self._sinks if s.is_healthy]
        if not targets:
            # все нездоровы — пробуем хотя бы первый (auto-recovery попытка)
            targets = self._sinks[:1]
        if not targets:
            return
        await asyncio.gather(
            *(s.write(record) for s in targets), return_exceptions=True
        )

    async def aclose(self) -> None:
        """Корректно закрыть все sink-ы (flush + close)."""
        for sink in self._sinks:
            try:
                await sink.flush()
            except Exception:  # noqa: BLE001 — sink-ошибки не должны прерывать close
                _INTERNAL_LOG.warning("flush failed for sink %s", sink.name)
            try:
                await sink.close()
            except Exception:  # noqa: BLE001
                _INTERNAL_LOG.warning("close failed for sink %s", sink.name)
        self._sinks.clear()


# ---------------------------------------------------------------------- module-level
_router: SinkRouter | Any | None = None
_router_lock = threading.Lock()


def configure_router(
    sinks: Iterable[LogSink] | None = None,
    *,
    profile: AppProfileChoices | None = None,
    batching: bool | None = None,
    batch_size: int = 100,
    flush_interval_ms: int = 200,
    queue_maxsize: int = 10_000,
) -> Any:
    """Настроить глобальный router.

    Args:
        sinks: Явный список sink-ов; если ``None`` — строится по profile.
        profile: Профиль (``dev_light`` / ``prod`` / ...). По умолчанию
            берётся из окружения.
        batching: Принудительно вкл/выкл async batching (Wave 7.7).
            При ``None`` — auto-on для ``staging`` / ``prod``.
        batch_size: Размер пачки в batching-режиме.
        flush_interval_ms: Период принудительного flush'а.
        queue_maxsize: Лимит очереди (защита от unbounded growth).

    Returns:
        :class:`SinkRouter` либо :class:`BatchingSinkRouter` (зависит от
        ``batching``).
    """
    global _router
    with _router_lock:
        active = profile if profile is not None else get_active_profile()
        chosen = list(sinks) if sinks is not None else build_sinks_for_profile(active)
        base = SinkRouter(chosen)

        use_batching = batching
        if use_batching is None:
            use_batching = active in (AppProfileChoices.staging, AppProfileChoices.prod)

        if use_batching:
            from src.infrastructure.logging.batching_router import BatchingSinkRouter

            _router = BatchingSinkRouter(
                base,
                batch_size=batch_size,
                flush_interval_ms=flush_interval_ms,
                queue_maxsize=queue_maxsize,
            )
        else:
            _router = base
        return _router


def get_router() -> Any:
    """Получить (или лениво создать) глобальный router.

    Если router ещё не инициализирован явно через :func:`configure_router`,
    создаёт :class:`SinkRouter` (без batching) на основе активного профиля
    окружения. Безопасен для использования в structlog-processor'ах в
    pre-init контексте.
    """
    global _router
    if _router is None:
        with _router_lock:
            if _router is None:
                _router = SinkRouter(build_sinks_for_profile())
    return _router


def is_router_configured() -> bool:
    """Возвращает ``True``, если глобальный :class:`SinkRouter` уже инициализирован.

    Используется в :func:`route_to_sinks`, чтобы избежать ленивого
    создания router'а в pre-init и тестовых контекстах: до явного
    вызова :func:`configure_router` processor работает как no-op.
    """
    return _router is not None


def reset_router() -> None:
    """Сбросить глобальный :class:`SinkRouter` (для тестов).

    Не вызывает ``aclose`` — это ответственность вызывающего кода.
    """
    global _router
    with _router_lock:
        _router = None


# ---------------------------------------------------------------------- structlog processor
def route_to_sinks(
    _logger: Any, _method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Structlog processor — fan-out event_dict во все активные sink-ы.

    Должен быть подключён в structlog-pipeline ПОСЛЕ всех обогащающих
    processor-ов, но ДО final renderer (поскольку sinks сами сериализуют
    event_dict через ``orjson``).

    Вызовы structlog синхронные, поэтому:

    1. Если есть запущенный event loop в текущем потоке — создаём
       :class:`asyncio.Task` (fire-and-forget); запись попадёт в sinks
       на ближайшей итерации loop.
    2. Если loop не запущен (например, на старте приложения или в
       sync-контексте) — запускаем ``router.dispatch`` в отдельном
       потоке через ``asyncio.run``; это блокирует только worker-thread,
       не event loop.

    Processor возвращает ``event_dict`` без изменений — он не должен
    мешать дальнейшему рендерингу.

    Если глобальный router ещё не инициализирован явно через
    :func:`configure_router` — processor работает как no-op
    (избегаем ленивого spawn'а sink-ов и dispatch-потоков в pre-init
    и тестовых контекстах).
    """
    if not is_router_configured():
        return event_dict
    router = get_router()
    snapshot = dict(event_dict)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        loop.create_task(router.dispatch(snapshot))
    else:
        threading.Thread(
            target=lambda: asyncio.run(router.dispatch(snapshot)),
            name="log-sink-dispatch",
            daemon=True,
        ).start()

    return event_dict
