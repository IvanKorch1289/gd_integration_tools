"""WindowedDedupProcessor и WindowedCollectProcessor — временно́е окно дедупликации.

CDC паттерн: несколько UPDATE-событий одной записи за N секунд → только финальное состояние.

WindowedDedupProcessor:
    Отслеживает ключи в скользящем окне. Первое сообщение проходит,
    последующие обновляют хранимое состояние, но ОСТАНАВЛИВАЮТСЯ.
    Метод ``get_latest(key, prefix)`` возвращает актуальное состояние.

    Режимы:
        first   — проходит первое сообщение в окне, остальные с тем же ключом — стоп.
        last    — проходит первое сообщение, остальные обновляют хранимое
                  (latest) состояние и стоп; используйте ``get_latest()`` для
                  получения финального значения после окна.
        unique  — проходят только сообщения с уникальным телом; точные дубли — стоп.

WindowedCollectProcessor:
    Накапливает сообщения в буфере Redis. Каждое входящее сообщение
    ОСТАНАВЛИВАЕТСЯ (буферизуется). Когда окно истекает (обнаруживается при
    поступлении следующего сообщения с тем же ключом), накопленный батч
    дедублицируется и инжектируется в exchange как ``inject_as``-свойство.

    Таким образом первое сообщение НОВОГО окна несёт в себе батч предыдущего.

MulticastRoutesProcessor:
    Fan-out на зарегистрированные route_id из RouteRegistry.
    Выполняет каждый маршрут параллельно и агрегирует результаты.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from src.dsl.engine.context import ExecutionContext
from src.dsl.engine.exchange import Exchange
from src.dsl.engine.processors.base import BaseProcessor

__all__ = ("WindowedDedupProcessor", "WindowedCollectProcessor")

_logger = logging.getLogger("dsl.eip.windowed")

_MODES = frozenset({"first", "last", "unique"})


def _extract_path(body: Any, path: str) -> Any:
    """Извлекает значение из вложенного dict по точечному пути (``a.b.c``)."""
    node: Any = body
    for part in path.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


def _serialize(body: Any) -> str:
    try:
        return json.dumps(body, ensure_ascii=False, sort_keys=True)
    except TypeError, ValueError:
        return str(body)


# ---------------------------------------------------------------------------
# WindowedDedupProcessor
# ---------------------------------------------------------------------------


class WindowedDedupProcessor(BaseProcessor):
    """Дедупликация сообщений в скользящем окне с Redis-персистентностью.

    Каждое сообщение имеет ключ (извлекается из ``key_from``).
    В рамках одного окна (``window_seconds``) обрабатывается не более
    одного уникального значения для каждого ключа.

    Args:
        key_from: Точечный путь к ключу в теле сообщения (напр. ``body.entity_id``).
        key_prefix: Префикс Redis-ключа для изоляции пространства имён.
        window_seconds: Длительность окна в секундах.
        mode: Режим дедупликации — ``first`` | ``last`` | ``unique``.
        name: Имя процессора в трассе.

    Режимы:
        first  — первое сообщение в окне проходит, дубли — стоп.
        last   — первое сообщение проходит; каждый дубль обновляет
                 хранимое состояние («latest»), но останавливается.
                 ``get_latest(key, prefix)`` возвращает финальное значение.
        unique — дедупликация по содержимому тела; повторные — стоп.
    """

    def __init__(
        self,
        *,
        key_from: str,
        key_prefix: str = "dedup",
        window_seconds: int = 60,
        mode: str = "first",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"windowed_dedup({mode},{window_seconds}s)")
        if mode not in _MODES:
            raise ValueError(
                f"WindowedDedupProcessor: неверный mode={mode!r}. Допустимые: {_MODES}."
            )
        self._key_from = key_from
        self._prefix = key_prefix
        self._window = window_seconds
        self._mode = mode

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Применяет оконную дедупликацию к входящему exchange."""
        try:
            from src.infrastructure.clients.storage.redis import redis_client

            key = str(_extract_path(exchange.in_message.body, self._key_from) or "")
            if not key:
                _logger.debug("windowed_dedup: пустой ключ, сообщение проходит")
                return

            serialized = _serialize(exchange.in_message.body)
            match self._mode:
                case "first":
                    await self._apply_first(exchange, key, serialized, redis_client)
                case "last":
                    await self._apply_last(exchange, key, serialized, redis_client)
                case "unique":
                    await self._apply_unique(exchange, key, serialized, redis_client)
        except Exception as exc:
            _logger.warning(
                "windowed_dedup: Redis недоступен, сообщение проходит: %s", exc
            )

    async def _apply_first(
        self, exchange: Exchange[Any], key: str, serialized: str, redis_client: Any
    ) -> None:
        """Первый в окне проходит, дубли — стоп."""
        redis_key = f"windowed:dedup:first:{self._prefix}:{key}"
        is_new = await redis_client.execute(
            "queue", lambda c: c.set(redis_key, "1", nx=True, ex=self._window)
        )
        if not is_new:
            _logger.debug("windowed_dedup(first): дубль ключа %r — стоп", key)
            exchange.stop()

    async def _apply_last(
        self, exchange: Exchange[Any], key: str, serialized: str, redis_client: Any
    ) -> None:
        """Первый в окне проходит; каждый дубль обновляет хранимое latest и стоп."""
        redis_key = f"windowed:dedup:last:{self._prefix}:{key}"
        # Атомарная SET NX — только если ключа нет
        is_new = await redis_client.execute(
            "queue", lambda c: c.set(redis_key, serialized, nx=True, ex=self._window)
        )
        if is_new:
            # Первое вхождение в окне — проходит
            return
        # Обновляем хранимое latest (без сброса TTL — окно не продлевается)
        await redis_client.execute(
            "queue", lambda c: c.set(redis_key, serialized, keepttl=True)
        )
        _logger.debug("windowed_dedup(last): обновлено latest для ключа %r — стоп", key)
        exchange.stop()

    async def _apply_unique(
        self, exchange: Exchange[Any], key: str, serialized: str, redis_client: Any
    ) -> None:
        """Дедупликация по содержимому тела — дубли — стоп."""
        body_hash = hashlib.sha256(serialized.encode()).hexdigest()[:16]
        redis_key = f"windowed:dedup:unique:{self._prefix}:{key}"
        is_new = await redis_client.execute(
            "queue", lambda c: c.sadd(redis_key, body_hash)
        )
        if is_new:
            await redis_client.execute(
                "queue", lambda c: c.expire(redis_key, self._window)
            )
        else:
            _logger.debug("windowed_dedup(unique): точный дубль ключа %r — стоп", key)
            exchange.stop()

    def to_spec(self) -> dict:
        """YAML-spec для round-trip сериализации WindowedDedupProcessor."""
        return {
            "windowed_dedup": {
                "key_from": self._key_from,
                "key_prefix": self._prefix,
                "window_seconds": self._window,
                "mode": self._mode,
            }
        }

    async def get_latest(self, key: str) -> Any | None:
        """Возвращает хранимое latest-состояние для ключа (только mode=last).

        Returns:
            Десериализованное тело последнего сообщения или None.
        """
        try:
            from src.infrastructure.clients.storage.redis import redis_client

            redis_key = f"windowed:dedup:last:{self._prefix}:{key}"
            raw = await redis_client.execute("queue", lambda c: c.get(redis_key))
            if raw is None:
                return None
            if isinstance(raw, bytes):
                raw = raw.decode()
            return json.loads(raw)
        except Exception as exc:
            _logger.warning("windowed_dedup.get_latest: %s", exc)
            return None


# ---------------------------------------------------------------------------
# WindowedCollectProcessor
# ---------------------------------------------------------------------------


class WindowedCollectProcessor(BaseProcessor):
    """Накопление сообщений в скользящем окне с дедупликацией и batching.

    Каждое входящее сообщение буферизуется в Redis (RPUSH + EXPIRE).
    Exchange ОСТАНАВЛИВАЕТСЯ — в downstream не идёт немедленно.

    Когда следующее сообщение с тем же ключом приходит ПОСЛЕ истечения окна,
    накопленный батч дедублицируется и инжектируется в exchange как свойство
    ``inject_as``. Это сообщение проходит downstream (не останавливается).

    Lazy-flush паттерн: батч N-го окна выбрасывается с первым сообщением (N+1)-го.

    Args:
        key_from: Точечный путь к ключу группировки (напр. ``body.table_name``).
        window_seconds: Длительность окна в секундах.
        dedup_by: Точечный путь к полю дедупликации внутри каждого сообщения.
        dedup_mode: ``first`` | ``last`` — какое значение сохранять при дедупликации.
        inject_as: Имя exchange-свойства для инжекции батча.
        name: Имя процессора в трассе.
    """

    def __init__(
        self,
        *,
        key_from: str,
        window_seconds: int = 60,
        dedup_by: str,
        dedup_mode: str = "last",
        inject_as: str = "collected_batch",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"windowed_collect({window_seconds}s)")
        if dedup_mode not in {"first", "last"}:
            raise ValueError(
                f"WindowedCollectProcessor: неверный dedup_mode={dedup_mode!r}."
            )
        self._key_from = key_from
        self._window = window_seconds
        self._dedup_by = dedup_by
        self._dedup_mode = dedup_mode
        self._inject_as = inject_as

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Добавляет сообщение в буфер; при смене окна — инжектирует батч."""
        try:
            from src.infrastructure.clients.storage.redis import redis_client

            key = str(_extract_path(exchange.in_message.body, self._key_from) or "")
            if not key:
                return

            buf_key = f"windowed:collect:buf:{key}"
            win_key = f"windowed:collect:win:{key}"

            # Проверяем — активно ли предыдущее окно
            ttl = await redis_client.execute("queue", lambda c: c.ttl(win_key))

            if ttl > 0:
                # Окно активно — буферизуем и стоп
                serialized = _serialize(exchange.in_message.body)
                await redis_client.execute(
                    "queue", lambda c: c.rpush(buf_key, serialized)
                )
                exchange.stop()
                return

            # Окно истекло или никогда не было — lazy-flush предыдущего батча
            batch = await self._flush_and_reset(key, buf_key, win_key, redis_client)

            if batch:
                # Инжектируем батч в текущий exchange (он проходит downstream)
                exchange.set_property(self._inject_as, batch)
                _logger.debug(
                    "windowed_collect: flush ключа %r → %d записей", key, len(batch)
                )
            else:
                # Первое сообщение — стартуем новое окно, стоп
                serialized = _serialize(exchange.in_message.body)
                await redis_client.execute(
                    "queue", lambda c: c.rpush(buf_key, serialized)
                )
                exchange.stop()
        except Exception as exc:
            _logger.warning(
                "windowed_collect: Redis недоступен, сообщение проходит: %s", exc
            )

    async def _flush_and_reset(
        self, key: str, buf_key: str, win_key: str, redis_client: Any
    ) -> list[Any]:
        """Читает и очищает буфер; открывает новое окно."""
        raw_items: list[bytes] = await redis_client.execute(
            "queue", lambda c: c.lrange(buf_key, 0, -1)
        )
        # Сбросить буфер и открыть новое окно
        await redis_client.execute("queue", lambda c: c.delete(buf_key))
        await redis_client.execute(
            "queue", lambda c: c.set(win_key, "1", ex=self._window)
        )

        if not raw_items:
            return []

        items = []
        for raw in raw_items:
            try:
                text = raw.decode() if isinstance(raw, bytes) else raw
                items.append(json.loads(text))
            except Exception:  # noqa: BLE001, S112
                continue

        return _dedup_batch(items, by=self._dedup_by, mode=self._dedup_mode)

    def to_spec(self) -> dict:
        """YAML-spec для round-trip сериализации WindowedCollectProcessor."""
        return {
            "windowed_collect": {
                "key_from": self._key_from,
                "dedup_by": self._dedup_by,
                "window_seconds": self._window,
                "dedup_mode": self._dedup_mode,
                "inject_as": self._inject_as,
            }
        }

    async def get_current_batch(self, key: str) -> list[Any]:
        """Возвращает текущее содержимое буфера (без сброса) — для тестов.

        Args:
            key: Значение ключа группировки.

        Returns:
            Список дедублицированных тел сообщений.
        """
        try:
            from src.infrastructure.clients.storage.redis import redis_client

            buf_key = f"windowed:collect:buf:{key}"
            raw_items: list[bytes] = await redis_client.execute(
                "queue", lambda c: c.lrange(buf_key, 0, -1)
            )
            items = []
            for raw in raw_items:
                try:
                    text = raw.decode() if isinstance(raw, bytes) else raw
                    items.append(json.loads(text))
                except Exception:  # noqa: BLE001, S112
                    continue
            return _dedup_batch(items, by=self._dedup_by, mode=self._dedup_mode)
        except Exception as exc:
            _logger.warning("windowed_collect.get_current_batch: %s", exc)
            return []


def _dedup_batch(items: list[Any], *, by: str, mode: str) -> list[Any]:
    """Дедублицирует список по полю ``by`` в режиме ``mode`` (first/last)."""
    seen: dict[str, Any] = {}
    for item in items:
        dedup_key = str(_extract_path(item, by) or "")
        if mode == "first":
            seen.setdefault(dedup_key, item)
        else:  # last
            seen[dedup_key] = item
    return list(seen.values())
