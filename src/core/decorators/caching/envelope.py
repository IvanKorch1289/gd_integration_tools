import time
from dataclasses import dataclass
from typing import Any

__all__ = ("CacheEnvelope", "MemoryCacheEntry")


@dataclass(slots=True)
class CacheEnvelope:
    """
    Унифицированная оболочка записи кэша.

    value:
        Полезное значение.

    ttl_seconds:
        Основной TTL записи. Пока он не истёк, запись считается fresh.

    stale_if_error_seconds:
        Дополнительное время жизни stale-значения.
        Используется только как fail-safe при ошибках источника данных.

    fresh_until:
        Время (monotonic), до которого запись считается fresh.

    stale_until:
        Время (monotonic), до которого запись можно вернуть как stale.
    """

    value: Any
    ttl_seconds: int | None
    stale_if_error_seconds: int
    fresh_until: float | None
    stale_until: float | None

    @staticmethod
    def _calc_deadline(seconds: int | None, now: float) -> float | None:
        if seconds is None or seconds <= 0:
            return None
        return now + seconds

    @classmethod
    def create(
        cls, value: Any, ttl_seconds: int | None, stale_if_error_seconds: int = 0
    ) -> "CacheEnvelope":
        now = time.monotonic()
        fresh_until = cls._calc_deadline(ttl_seconds, now)

        if fresh_until is None:
            stale_until = None
        else:
            stale_until = fresh_until + max(0, stale_if_error_seconds)

        return cls(
            value=value,
            ttl_seconds=ttl_seconds,
            stale_if_error_seconds=max(0, stale_if_error_seconds),
            fresh_until=fresh_until,
            stale_until=stale_until,
        )

    def renew(self) -> "CacheEnvelope":
        return self.create(
            value=self.value,
            ttl_seconds=self.ttl_seconds,
            stale_if_error_seconds=self.stale_if_error_seconds,
        )

    def is_fresh(self, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        return self.fresh_until is None or self.fresh_until > current

    def is_alive(self, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        return self.stale_until is None or self.stale_until > current

    def is_stale(self, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        return self.is_alive(current) and not self.is_fresh(current)

    def to_dict(self) -> dict[str, Any]:
        return {
            "__cache_envelope__": True,
            "value": self.value,
            "ttl_seconds": self.ttl_seconds,
            "stale_if_error_seconds": self.stale_if_error_seconds,
            "fresh_until": self.fresh_until,
            "stale_until": self.stale_until,
        }

    @classmethod
    def from_payload(cls, payload: Any) -> "CacheEnvelope":
        if isinstance(payload, dict) and payload.get("__cache_envelope__") is True:
            return cls(
                value=payload.get("value"),
                ttl_seconds=payload.get("ttl_seconds"),
                stale_if_error_seconds=payload.get("stale_if_error_seconds", 0),
                fresh_until=payload.get("fresh_until"),
                stale_until=payload.get("stale_until"),
            )

        return cls(
            value=payload,
            ttl_seconds=None,
            stale_if_error_seconds=0,
            fresh_until=None,
            stale_until=None,
        )


@dataclass(slots=True)
class MemoryCacheEntry:
    envelope: CacheEnvelope
