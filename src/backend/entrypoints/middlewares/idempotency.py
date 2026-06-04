"""Idempotency-Key middleware (Sprint 0 #12, V5 security constraint).

Тонкая обёртка над ``asgi_idempotency_header.IdempotencyHeaderMiddleware``
с собственным Redis NX backend для атомарной блокировки pending-ключей.

Архитектура backends:
* ``MemoryBackend`` (shipped) — для test/dev_light профилей.
* :class:`RedisNxBackend` — для prod. Использует ``SET NX EX`` чтобы
  гарантировать, что два конкурентных POST с одинаковым ``Idempotency-Key``
  не обработаются одновременно (второй получит 409 Conflict в течение
  ``pending_ttl`` секунд).

См. V5 в ``CLAUDE.md`` (Sprint 0 #12, security constraint).
"""

from __future__ import annotations

import logging
from typing import Any

import orjson
from fastapi.responses import JSONResponse
from idempotency_header_middleware import IdempotencyHeaderMiddleware
from idempotency_header_middleware.backends.base import Backend
from idempotency_header_middleware.backends.memory import MemoryBackend

__all__ = (
    "IDEMPOTENCY_HEADER",
    "IdempotencyHeaderMiddleware",
    "RedisNxBackend",
    "build_idempotency_backend",
)

IDEMPOTENCY_HEADER = "Idempotency-Key"

_logger = logging.getLogger(__name__)


class RedisNxBackend(Backend):
    """Idempotency backend поверх Redis с атомарным NX-блоком.

    Семантика V5:
    * ``store_idempotency_key`` → ``SET pending:<key> 1 NX EX <pending_ttl>``;
      возвращает ``True`` если ключ уже существовал (middleware ответит 409).
    * ``store_response_data`` → пишет полезную нагрузку в ``response:<key>``
      на ``response_ttl`` секунд; идентичен ``RedisBackend`` shipped'а.
    * ``clear_idempotency_key`` → удаляет pending-ключ, освобождая блок.

    Парам. ``pending_ttl`` (default 120s) — на случай зависшего worker'а:
    блок снимется автоматически.
    """

    def __init__(
        self,
        redis: Any,
        *,
        pending_ttl: int = 120,
        response_ttl: int = 60 * 60 * 24,
        pending_prefix: str = "idem:pending:",
        response_prefix: str = "idem:response:",
    ) -> None:
        self._redis = redis
        self._pending_ttl = pending_ttl
        self._response_ttl = response_ttl
        self._pending_prefix = pending_prefix
        self._response_prefix = response_prefix
        self.expiry = response_ttl

    def _pending_key(self, idempotency_key: str) -> str:
        return f"{self._pending_prefix}{idempotency_key}"

    def _response_keys(self, idempotency_key: str) -> tuple[str, str]:
        body_key = f"{self._response_prefix}{idempotency_key}"
        status_key = f"{self._response_prefix}{idempotency_key}:status"
        return body_key, status_key

    async def get_stored_response(self, idempotency_key: str) -> JSONResponse | None:
        body_key, status_key = self._response_keys(idempotency_key)
        payload = await self._redis.get(body_key)
        if payload is None:
            return None
        status_raw = await self._redis.get(status_key)
        status_code = int(status_raw) if status_raw is not None else 200
        return JSONResponse(orjson.loads(payload), status_code=status_code)

    async def store_response_data(
        self, idempotency_key: str, payload: dict, status_code: int
    ) -> None:
        body_key, status_key = self._response_keys(idempotency_key)
        body_bytes = orjson.dumps(payload)
        await self._redis.set(body_key, body_bytes, ex=self._response_ttl)
        await self._redis.set(status_key, str(status_code), ex=self._response_ttl)

    async def store_idempotency_key(self, idempotency_key: str) -> bool:
        """Атомарно резервирует pending-ключ через ``SET NX EX``.

        Returns:
            ``True`` если ключ уже существовал (запрос pending или дубль),
            ``False`` если успешно зарезервирован для текущего запроса.
        """
        reserved = await self._redis.set(
            self._pending_key(idempotency_key), b"1", nx=True, ex=self._pending_ttl
        )
        return not bool(reserved)

    async def clear_idempotency_key(self, idempotency_key: str) -> None:
        await self._redis.delete(self._pending_key(idempotency_key))


def build_idempotency_backend() -> Backend:
    """Фабрика backend'а на основе профиля приложения.

    * Production / staging: :class:`RedisNxBackend` поверх ``redis_client``
      (cache-kind), даёт V5-блокировку.
    * Test / dev_light: ``MemoryBackend`` (in-process), без Redis-зависимости.

    Ленивый импорт ``redis_client``: на момент инстанцирования middleware
    подключение может быть ещё не открыто — RedisNxBackend получает только
    callable-аксессор, а реальный клиент резолвится на первом обращении.
    """
    try:
        from src.backend.core.di.providers import get_redis_kv_client_provider
    except Exception as exc:  # pragma: no cover — DI-провайдер обязан существовать
        _logger.warning("Idempotency: DI redis-provider недоступен: %s", exc)
        return MemoryBackend()

    return RedisNxBackend(_LazyRedisProxy(get_redis_kv_client_provider))


class _LazyRedisProxy:
    """Резолвит redis-клиент при первом вызове async-метода.

    Нужен потому, что ``setup_middlewares`` выполняется до ``app.startup``,
    когда ``redis_client`` ещё не инициализирован. На каждом ``__call__``
    обращается к DI-провайдеру (singleton-кеш внутри провайдера).
    """

    def __init__(self, resolver: Any) -> None:
        self._resolver = resolver

    def _client(self) -> Any:
        return self._resolver()

    async def get(self, key: str) -> bytes | None:
        return await self._client().get(key)

    async def set(
        self, key: str, value: bytes | str, *, ex: int | None = None, nx: bool = False
    ) -> bool | None:
        return await self._client().set(key, value, ex=ex, nx=nx)

    async def delete(self, *keys: str) -> int:
        return await self._client().delete(*keys)
