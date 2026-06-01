import asyncio

__all__ = ("KeyLockManager",)


class KeyLockManager:
    """Per-key lock manager для защиты от cache stampede."""

    def __init__(self, acquire_timeout: float = 5.0) -> None:
        self._key_locks: dict[str, asyncio.Lock] = {}
        self._guard = asyncio.Lock()
        self.acquire_timeout = acquire_timeout

    async def get(self, key: str) -> asyncio.Lock:
        async with self._guard:
            lock = self._key_locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._key_locks[key] = lock
            return lock

    async def cleanup(self, key: str, lock: asyncio.Lock) -> None:
        async with self._guard:
            current = self._key_locks.get(key)
            if current is not lock:
                return
            if lock.locked():
                return
            waiters = getattr(lock, "_waiters", None)
            if waiters and any(not w.cancelled() for w in waiters):
                return
            self._key_locks.pop(key, None)
