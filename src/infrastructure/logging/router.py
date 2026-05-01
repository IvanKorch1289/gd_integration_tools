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
    "build_sinks_for_profile",
    "configure_router",
    "get_router",
    "route_to_sinks",
)

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
_router: SinkRouter | None = None
_router_lock = threading.Lock()


def configure_router(
    sinks: Iterable[LogSink] | None = None, *, profile: AppProfileChoices | None = None
) -> SinkRouter:
    """Настроить глобальный :class:`SinkRouter`.

    Если ``sinks`` не передан, sink-ы строятся из ``profile``
    (или активного профиля окружения) через :func:`build_sinks_for_profile`.
    """
    global _router
    with _router_lock:
        chosen = list(sinks) if sinks is not None else build_sinks_for_profile(profile)
        _router = SinkRouter(chosen)
        return _router


def get_router() -> SinkRouter:
    """Получить (или лениво создать) глобальный :class:`SinkRouter`."""
    global _router
    if _router is None:
        with _router_lock:
            if _router is None:
                _router = SinkRouter(build_sinks_for_profile())
    return _router


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
    """
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
