"""Контракт ``LogSink`` — асинхронный приёмник лог-записей.

Wave 2.5 (Roadmap V10): унификация logging-стека на structlog + LogSink.
``LogSink`` — это слой адаптера между structlog (источник event_dict) и
конкретным backend-транспортом (stdout, file, Graylog GELF, …).

Идея::

    structlog.processor → route_to_sinks(event_dict) → [Sink1, Sink2, ...]

Каждый sink:
    * полностью асинхронный (``write``/``flush``/``close`` — async);
    * имеет имя и флаг здоровья (для circuit-breaker / health-aggregator);
    * не должен бросать исключения наружу — отказ одного sink не должен
      ронять весь pipeline (router решает, что делать при ошибке).

Реализации живут в :mod:`src.infrastructure.logging.backends`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

__all__ = ("LogSink",)


class LogSink(ABC):
    """Асинхронный приёмник структурированных лог-записей.

    Атрибуты:
        name: уникальное имя sink-а — для метрик и логов о самом logging-стэке.
        is_healthy: текущее состояние транспорта. ``False`` означает,
            что router должен временно пропускать этот sink и/или
            переключаться на fallback (например, ``DiskRotatingLogSink``).

    Контракт реализаций:
        * Метод :meth:`write` обязан быть идемпотентным относительно ошибок:
          поймать exception и зафиксировать ``is_healthy = False``.
        * Метод :meth:`flush` сбрасывает буферы, если есть.
        * Метод :meth:`close` корректно закрывает ресурсы (сокет, файл).
    """

    name: str
    is_healthy: bool

    @abstractmethod
    async def write(self, record: dict[str, Any]) -> None:
        """Записать одну структурированную запись лога.

        Аргументы:
            record: словарь event_dict от structlog
                (поля ``event``, ``level``, ``timestamp``, контекст и т.д.).

        Не должен бросать наружу: при ошибке транспорта реализация
        обновляет :attr:`is_healthy` и возвращает управление.
        """

    @abstractmethod
    async def flush(self) -> None:
        """Сбросить буферы транспорта (если буферизация есть)."""

    @abstractmethod
    async def close(self) -> None:
        """Корректно завершить работу и освободить ресурсы."""
