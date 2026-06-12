"""DataStoreMixin (S39 W3a — n8n-style in-memory KV с TTL + thread-safety).

Adds ``RouteBuilder.data_store(name)`` -> workflow-scoped :class:`DataStore`.
Stdlib only; thread-safe via RLock; lazy TTL expiry на чтении; O(1) average.
"""

from __future__ import annotations

import threading
import time
from typing import Any

__all__ = ("DataStore", "DataStoreMixin")


class DataStore:
    """n8n-style in-memory KV with TTL + thread-safety (stdlib only)."""

    __slots__ = ("_backend", "_data", "_lock", "_name")

    def __init__(self, name: str, backend: str = "memory") -> None:
        self._name, self._backend = name, backend
        # value, expire_at (monotonic seconds) or None
        self._data: dict[str, tuple[Any, float | None]] = {}
        self._lock = threading.RLock()

    @property
    def name(self) -> str:
        """Имя store (например, ``"default"`` или ``"session_cache"``)."""
        return self._name

    @property
    def backend(self) -> str:
        """Backend identifier (``"memory"`` сегодня, ``"redis"`` в S97+)."""
        return self._backend

    @staticmethod
    def _alive(expire_at: float | None, now: float) -> bool:
        """TTL check: ``expire_at is None`` → бессрочно, иначе ``now < expire_at``."""
        return expire_at is None or now < expire_at

    def get(self, key: str, default: Any = None) -> Any:
        """Получить value по ``key``.

        Args:
            key: Ключ записи.
            default: Возвращается если ключ отсутствует или истёк TTL.

        Returns:
            Value или ``default``. Expired записи lazy-удаляются при access.
        """
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return default
            value, exp = entry
            if not self._alive(exp, time.monotonic()):
                self._data.pop(key, None)
                return default
            return value

    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        """Сохранить ``value`` под ``key``.

        Args:
            key: Ключ записи.
            value: Любой picklable value.
            ttl_seconds: TTL в секундах (``None`` = бессрочно).
        """
        with self._lock:
            exp = time.monotonic() + ttl_seconds if ttl_seconds is not None else None
            self._data[key] = (value, exp)

    def delete(self, key: str) -> bool:
        """Удалить запись.

        Returns:
            ``True`` если ключ существовал, ``False`` если нет.
        """
        with self._lock:
            return self._data.pop(key, None) is not None

    def has(self, key: str) -> bool:
        """Проверить наличие ключа (без получения value).

        Expired записи lazy-удаляются, как в :meth:`get`.
        """
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return False
            _, exp = entry
            if not self._alive(exp, time.monotonic()):
                self._data.pop(key, None)
                return False
            return True

    def keys(self) -> list[str]:
        """Список живых (non-expired) ключей."""
        with self._lock:
            now = time.monotonic()
            return [k for k, (_, e) in self._data.items() if self._alive(e, now)]

    def values(self) -> list[Any]:
        """Список живых values (порядок не гарантирован)."""
        with self._lock:
            now = time.monotonic()
            return [v for v, e in self._data.values() if self._alive(e, now)]

    def items(self) -> list[tuple[str, Any]]:
        """Список ``(key, value)`` для живых записей."""
        with self._lock:
            now = time.monotonic()
            return [(k, v) for k, (v, e) in self._data.items() if self._alive(e, now)]

    def clear(self) -> None:
        """Очистить все записи (atomic под lock)."""
        with self._lock:
            self._data.clear()

    def size(self) -> int:
        """Количество живых (non-expired) записей."""
        with self._lock:
            now = time.monotonic()
            return sum(1 for _, e in self._data.values() if self._alive(e, now))


class DataStoreMixin:
    """RouteBuilder mixin: ``.data_store(name)`` -> workflow-scoped :class:`DataStore`."""

    __slots__ = ()

    def data_store(self, name: str = "default", backend: str = "memory") -> DataStore:
        """Get-or-create named :class:`DataStore` (lazy, per-builder scope)."""
        stores: dict[str, DataStore] = getattr(self, "_data_stores", None)
        if stores is None:
            stores = {}
            object.__setattr__(self, "_data_stores", stores)
        ds = stores.get(name)
        if ds is None:
            ds = DataStore(name=name, backend=backend)
            stores[name] = ds
        return ds
