"""Redis-based реализация :class:`BreakerStateStorage` (DoD-9).

Wave ``[wave:s18/w0-goal-driven-sweep-4-redis-breaker-storage]``.

Назначение: реальная персистентность состояния circuit breaker'а в Redis,
чтобы после рестарта процесса :class:`InMemoryPybreakerAdapter` мог
``restore()``-нуться в то же состояние, в котором был до рестарта.

Контракт реализации:

* :meth:`save` — сериализует :class:`BreakerState` в JSON и пишет в
  ключ ``cb:state:{name}``;
* :meth:`load` — десериализует JSON и собирает :class:`BreakerState`;
* TTL опционален: длинные TTL допустимы (это «memory» CB-state).

Зависит от async-Redis-клиента (``redis.asyncio.Redis`` или совместимый
fake), который инжектируется в конструктор. Конкретный клиент не
импортируется здесь, чтобы тесты могли использовать ``fakeredis``
без зависимости.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from src.backend.core.utils.pybreaker_adapter import BreakerState

__all__ = ("RedisBreakerStateStorage",)

_logger = logging.getLogger("infrastructure.resilience.redis_breaker_storage")

_KEY_TEMPLATE = "cb:state:{name}"


class RedisBreakerStateStorage:
    """Persistent storage CB-state поверх async Redis-клиента.

    Реализует :class:`src.backend.core.utils.pybreaker_adapter.
    BreakerStateStorage` (структурно через Protocol).

    Args:
        redis_client: Async Redis-совместимый клиент (``redis.asyncio.Redis``
            или fake) с методами ``get(key) -> bytes|str|None`` и
            ``set(key, value, ex=...)``.
        ttl_seconds: Опциональный TTL для записи (None — без expire).
        key_prefix: Опциональный префикс для namespace-изоляции в
            shared Redis. По умолчанию — ``cb:state:``.
    """

    def __init__(
        self,
        redis_client: Any,
        *,
        ttl_seconds: int | None = None,
        key_prefix: str = "cb:state:",
    ) -> None:
        self._redis = redis_client
        self._ttl = ttl_seconds
        self._key_prefix = key_prefix

    def _key(self, name: str) -> str:
        """Сформировать ключ Redis из имени breaker'а."""
        return f"{self._key_prefix}{name}"

    async def save(self, state: BreakerState) -> None:
        """Сохранить snapshot в Redis.

        Args:
            state: Snapshot для записи.
        """
        payload = json.dumps(
            {
                "state": state.state,
                "fail_counter": state.fail_counter,
                "last_failure_at_iso": state.last_failure_at_iso,
            },
            separators=(",", ":"),
        )
        key = self._key(state.name)
        try:
            if self._ttl is not None:
                await self._redis.set(key, payload, ex=self._ttl)
            else:
                await self._redis.set(key, payload)
        except Exception as exc:  # noqa: BLE001
            # Сетевая ошибка не должна валить CB — лог + продолжаем.
            _logger.warning(
                "RedisBreakerStateStorage save(%s) failed: %s", state.name, exc
            )

    async def load(self, name: str) -> BreakerState | None:
        """Прочитать snapshot по имени breaker'а.

        Args:
            name: Имя breaker'а.

        Returns:
            BreakerState или None если ключа нет / ошибка чтения.
        """
        key = self._key(name)
        try:
            raw = await self._redis.get(key)
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "RedisBreakerStateStorage load(%s) failed: %s", name, exc
            )
            return None

        if raw is None:
            return None
        if isinstance(raw, bytes | bytearray):
            try:
                raw = raw.decode("utf-8")
            except UnicodeDecodeError:
                _logger.warning(
                    "RedisBreakerStateStorage load(%s): invalid UTF-8", name
                )
                return None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            _logger.warning(
                "RedisBreakerStateStorage load(%s): invalid JSON payload", name
            )
            return None
        return BreakerState(
            name=name,
            state=str(data.get("state", "closed")),
            fail_counter=int(data.get("fail_counter", 0)),
            last_failure_at_iso=str(data.get("last_failure_at_iso", "")),
        )
