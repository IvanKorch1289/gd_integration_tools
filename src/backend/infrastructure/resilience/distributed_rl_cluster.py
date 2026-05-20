"""Distributed token-bucket rate-limiter поверх Redis Cluster (Sprint 11 K2 W1).

Реализует per-tenant token-bucket с использованием атомарного Lua-скрипта:

* ``EVALSHA`` на Redis Cluster c hashtag-routing (``{tenant}``) для
  однонодовой консистентности;
* атомарный refill (tokens_per_second × elapsed) + decrement requested;
* возвращает ``(allowed: int, remaining: int, retry_after_ms: int)``.

Поведение feature-flag:
* ``feature_flags.distributed_rl_redis_cluster=True`` → middleware
  использует этот лимитер;
* при OFF — in-memory legacy backend.

Lua-скрипт минималистичен (без CL.THROTTLE-зависимости): возможна работа
с любой совместимой Redis-сборкой.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

__all__ = ("DistributedRedisRateLimiter", "TokenBucketResult")

logger = logging.getLogger("infra.resilience.distributed_rl")

# Lua-скрипт: атомарный token-bucket per-key.
# KEYS[1] = bucket-key (e.g. ``rl:{tenant_id}``)
# ARGV: capacity, refill_per_sec, tokens_requested, now_ms
# Returns: {allowed, remaining_tokens, retry_after_ms}
_TOKEN_BUCKET_LUA = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_per_sec = tonumber(ARGV[2])
local requested = tonumber(ARGV[3])
local now_ms = tonumber(ARGV[4])

local data = redis.call('HMGET', key, 'tokens', 'last_ms')
local tokens = tonumber(data[1]) or capacity
local last_ms = tonumber(data[2]) or now_ms

local elapsed_ms = math.max(0, now_ms - last_ms)
local refill = (elapsed_ms / 1000.0) * refill_per_sec
tokens = math.min(capacity, tokens + refill)

local allowed = 0
local retry_after_ms = 0
if tokens >= requested then
    tokens = tokens - requested
    allowed = 1
else
    local deficit = requested - tokens
    retry_after_ms = math.ceil((deficit / refill_per_sec) * 1000.0)
end

redis.call('HMSET', key, 'tokens', tokens, 'last_ms', now_ms)
redis.call('EXPIRE', key, 3600)
return {allowed, tokens, retry_after_ms}
"""


@dataclass(frozen=True, slots=True)
class TokenBucketResult:
    """Результат одной попытки acquire."""

    allowed: bool
    remaining: float
    retry_after_ms: int


class DistributedRedisRateLimiter:
    """Per-tenant token-bucket поверх RedisClusterAdapter.

    Args:
        adapter: :class:`RedisClusterAdapter` с подключённым кластером.
        capacity: Размер bucket'а (макс. количество токенов на tenant).
        refill_per_second: Скорость пополнения (tokens / sec).
        key_prefix: Префикс ключей в Redis. Hashtag ``{tenant_id}``
            обеспечивает hash-slot routing на один узел.
    """

    def __init__(
        self,
        adapter: object,  # RedisClusterAdapter, без жёсткой типизации для тестов
        *,
        capacity: int = 100,
        refill_per_second: float = 10.0,
        key_prefix: str = "rl",
    ) -> None:
        self._adapter = adapter
        self._capacity = capacity
        self._refill = refill_per_second
        self._key_prefix = key_prefix
        self._script_sha: str | None = None

    def _key(self, tenant_id: str) -> str:
        # Hashtag ``{tenant_id}`` гарантирует одно-нодовый routing.
        return f"{self._key_prefix}:{{{tenant_id}}}"

    async def _ensure_script(self) -> str:
        """SCRIPT LOAD lua-скрипта с кешированием sha1."""
        if self._script_sha is not None:
            return self._script_sha
        client = getattr(self._adapter, "client", self._adapter)
        sha = await client.script_load(_TOKEN_BUCKET_LUA)
        self._script_sha = sha if isinstance(sha, str) else sha.decode("ascii")
        return self._script_sha

    async def acquire(
        self,
        tenant_id: str,
        *,
        tokens: int = 1,
    ) -> TokenBucketResult:
        """Попытаться взять ``tokens`` из бакета tenant'а.

        Returns:
            :class:`TokenBucketResult` с allowed/remaining/retry_after_ms.
            При недоступности Redis — fail-open (allowed=True, remaining=0).
        """
        now_ms = int(time.time() * 1000)
        key = self._key(tenant_id)

        try:
            sha = await self._ensure_script()
            client = getattr(self._adapter, "client", self._adapter)
            raw = await client.evalsha(
                sha,
                1,
                key,
                self._capacity,
                self._refill,
                tokens,
                now_ms,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "DistributedRedisRateLimiter fail-open for tenant=%s: %s",
                tenant_id,
                exc,
            )
            return TokenBucketResult(allowed=True, remaining=0.0, retry_after_ms=0)

        # Lua-скрипт возвращает [allowed, remaining, retry_after_ms].
        allowed = bool(int(raw[0]))
        remaining = float(raw[1])
        retry_after = int(raw[2])
        return TokenBucketResult(
            allowed=allowed, remaining=remaining, retry_after_ms=retry_after
        )

    async def reset(self, tenant_id: str) -> None:
        """Полный сброс bucket'а tenant'а (admin-операция)."""
        client = getattr(self._adapter, "client", self._adapter)
        try:
            await client.delete(self._key(tenant_id))
        except Exception as exc:  # noqa: BLE001
            logger.warning("rl reset failed for tenant=%s: %s", tenant_id, exc)
