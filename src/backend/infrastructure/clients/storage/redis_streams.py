"""Stream-транспорт для audit/телеметрии: Redis Streams или in-memory.

Зачем отдельный модуль
----------------------
Потребители (audit-replay middleware, ``services.audit.replay_query``,
LLM-judge) работают через один контракт: ``add_to_stream`` / ``read_stream``.
Раньше единственной реализацией был Redis, из-за чего на профилях без Redis
(``dev_light``: ``redis.enabled=false``) audit-записи не писались, а в лог
падало ``Неизвестный ключ infrastructure-модуля:
'clients.storage.redis_streams'`` — DI-ключ не был зарегистрирован в
``INFRA_MODULES``, и резолв падал до обращения к Redis.

Контракт
--------
* ``add_to_stream(stream_name, data) -> str`` — записать событие, вернуть id;
* ``read_stream(stream_name, count, start_id) -> list[dict]`` — прочитать
  записи (плоские dict'ы, как ожидает audit-replay). ``start_id`` —
 exclusive (как ``XREAD`` в Redis): возвращаются записи строго после указанной.

Транспорт выбирается по ``settings.redis.enabled``:

* Redis включён (staging/prod) → Redis Streams;
* Redis выключен (dev/dev_light) → in-memory: audit работает локально,
  подключение к Redis не требуется.
"""

from __future__ import annotations

from typing import Any

from src.backend.core.logging import get_logger

__all__ = ("InMemoryStreamClient", "RedisStreamClient", "redis_stream_client")

_logger = get_logger("infra.redis_streams")

#: Максимум записей, хранимых в одном in-memory потоке (защита от роста).
_MAX_IN_MEMORY_ENTRIES = 1000


def _entry_seq(entry_id: str) -> int:
    """Возвращает числовую часть id записи (``"12-0"`` → ``12``).

    Args:
        entry_id: Идентификатор записи.

    Returns:
        int: Порядковый номер записи (0 — если разобрать не удалось).

    """
    head = entry_id.split("-", 1)[0]
    return int(head) if head.isdigit() else 0


class InMemoryStreamClient:
    """In-memory реализация stream-контракта (Redis выключен).

    Живёт в памяти процесса: записи видны только внутри него. Используется
    на dev-профилях, где Redis не поднят, чтобы audit-replay и LLM-judge
    работали без внешних зависимостей.
    """

    def __init__(self) -> None:
        """Инициализирует пустое хранилище потоков."""
        self._streams: dict[str, list[dict[str, Any]]] = {}
        self._counter = 0

    async def add_to_stream(self, stream_name: str, data: dict[str, Any]) -> str:
        """Записывает событие в поток.

        Args:
            stream_name: Имя потока.
            data: Данные события.

        Returns:
            str: Идентификатор записи.

        """
        self._counter += 1
        entry_id = f"{self._counter}-0"
        entries = self._streams.setdefault(stream_name, [])
        entries.append({"id": entry_id, **data})
        if len(entries) > _MAX_IN_MEMORY_ENTRIES:
            del entries[: len(entries) - _MAX_IN_MEMORY_ENTRIES]
        return entry_id

    async def read_stream(
        self, stream_name: str, count: int = 100, start_id: str = "-"
    ) -> list[dict[str, Any]]:
        """Читает записи потока.

        Args:
            stream_name: Имя потока.
            count: Максимум записей (0 — без ограничения).
            start_id: Начать строго после записи с этим id (``"-"`` — с начала).

        Returns:
            list[dict[str, Any]]: Записи потока (плоские dict'ы).

        """
        entries = self._streams.get(stream_name, [])
        if start_id and start_id != "-":
            after = _entry_seq(start_id)
            entries = [e for e in entries if _entry_seq(str(e.get("id", ""))) > after]
        if count and count > 0:
            entries = entries[-count:]
        return list(entries)


class RedisStreamClient:
    """Адаптер ``RedisClient`` → stream-контракт (``add_to_stream``/``read_stream``).

    Args:
        client: Инстанс ``RedisClient`` (инфраструктурный redis-клиент).

    """

    def __init__(self, client: Any) -> None:
        """Запоминает redis-клиент."""
        self._client = client

    async def add_to_stream(self, stream_name: str, data: dict[str, Any]) -> str:
        """Публикует событие в Redis Stream.

        Args:
            stream_name: Имя потока.
            data: Данные события.

        Returns:
            str: Идентификатор записи.

        """
        return str(await self._client.stream_publish(stream_name, data))

    async def read_stream(
        self, stream_name: str, count: int = 100, start_id: str = "-"
    ) -> list[dict[str, Any]]:
        """Читает записи Redis Stream.

        Args:
            stream_name: Имя потока.
            count: Максимум записей.
            start_id: Начать строго после записи с этим id (``"-"`` — с начала).

        Returns:
            list[dict[str, Any]]: Записи потока (плоские dict'ы + ``id``).

        """
        records = await self._client.stream_read(
            stream_name, last_id=start_id or "-", count=count, block_ms=1
        )
        return [
            {"id": str(item.get("id", "")), **dict(item.get("data") or {})}
            for item in records or []
        ]


class StreamClient:
    """Транспорт-селектор: Redis Streams или in-memory.

    Решение принимается на каждый вызов — hot-reload настроек
    (``redis.enabled``) применяется без перезапуска процесса.
    """

    def __init__(self) -> None:
        """Инициализирует транспорты (in-memory создаётся сразу)."""
        self._memory = InMemoryStreamClient()
        self._redis: RedisStreamClient | None = None

    def _backend(self) -> Any:
        """Возвращает активный транспорт (Redis или in-memory)."""
        from src.backend.core.config.settings import settings

        if not settings.redis.enabled:
            return self._memory
        if self._redis is None:
            from src.backend.infrastructure.clients.storage.redis import RedisClient

            self._redis = RedisStreamClient(RedisClient(settings.redis))
        return self._redis

    async def add_to_stream(self, stream_name: str, data: dict[str, Any]) -> str:
        """Записывает событие в активный транспорт.

        Args:
            stream_name: Имя потока.
            data: Данные события.

        Returns:
            str: Идентификатор записи.

        """
        return str(await self._backend().add_to_stream(stream_name, data))

    async def read_stream(
        self, stream_name: str, count: int = 100, start_id: str = "-"
    ) -> list[dict[str, Any]]:
        """Читает записи из активного транспорта.

        Args:
            stream_name: Имя потока.
            count: Максимум записей.
            start_id: Начать строго после записи с этим id (``"-"`` — с начала).

        Returns:
            list[dict[str, Any]]: Записи потока (плоские dict'ы).

        """
        records = await self._backend().read_stream(
            stream_name, count=count, start_id=start_id
        )
        return list(records or [])


#: Синглтон stream-транспорта (DI-ключ ``clients.storage.redis_streams``).
redis_stream_client = StreamClient()
