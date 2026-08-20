"""Unit-тесты для QueryResultCache (S38.2)."""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.core.interfaces.cache import CacheBackend
from src.backend.infrastructure.cache.backends.memory import MemoryBackend
from src.backend.infrastructure.database.query_result_cache import (
    JsonSerializer,
    OrjsonSerializer,
    PickleSerializer,
    QueryResultCache,
    get_default_serializer,
)

pytestmark = pytest.mark.unit


class TestSerializers:
    def test_pickle_roundtrip(self):
        ser = PickleSerializer()
        data = {"rows": [(1, "a"), (2, "b")], "meta": {"count": 2}}
        assert ser.loads(ser.dumps(data)) == data

    def test_json_roundtrip(self):
        ser = JsonSerializer()
        data = {"rows": [[1, "a"], [2, "b"]], "count": 2}
        assert ser.loads(ser.dumps(data)) == data

    def test_json_datetime_fallback(self):
        from datetime import datetime

        ser = JsonSerializer()
        dt = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        raw = ser.dumps({"dt": dt})
        assert b"2024-01-01" in raw

    @pytest.mark.skipif(
        __import__("importlib.util").util.find_spec("orjson") is None,
        reason="orjson not installed",
    )
    def test_orjson_roundtrip(self):
        ser = OrjsonSerializer()
        data = {"rows": [[1, "a"], [2, "b"]], "count": 2}
        assert ser.loads(ser.dumps(data)) == data

    def test_get_default_serializer(self):
        ser = get_default_serializer()
        # Cycle 34 audit: pickle is no longer the default (RCE-vector risk).
        # orjson is always the default since it's a hard dep.
        assert isinstance(ser, OrjsonSerializer), (
            f"Expected OrjsonSerializer, got {type(ser).__name__}. "
            "Pickle is opt-in only since cycle 34."
        )

    def test_pickle_serializer_still_available_for_explicit_optin(self):
        """PickleSerializer remains importable for callers who explicitly
        need pickle semantics (e.g. cross-process object transport).
        """
        ser = PickleSerializer()
        assert isinstance(ser, PickleSerializer)
        # Roundtrip works for plain dicts (which pickle handles natively)
        obj = {"x": 42, "nested": {"y": [1, 2, 3]}}
        assert ser.loads(ser.dumps(obj)) == obj


class TestQueryResultCache:
    @pytest.fixture
    async def cache(self):
        backend = MemoryBackend(maxsize=100)
        return QueryResultCache(backend, prefix="qrc", default_ttl=300)

    @pytest.mark.asyncio
    async def test_get_missing_returns_none(self, cache):
        result = await cache.get("main", "SELECT 1")
        assert result is None

    @pytest.mark.asyncio
    async def test_set_and_get(self, cache):
        sql = "SELECT * FROM users WHERE id = :id"
        params = {"id": 42}
        rows = [{"id": 42, "name": "Alice"}]
        await cache.set("main", sql, params, rows)
        assert await cache.get("main", sql, params) == rows

    @pytest.mark.asyncio
    async def test_different_params_different_keys(self, cache):
        sql = "SELECT * FROM users WHERE id = :id"
        await cache.set("main", sql, {"id": 1}, ["a"])
        await cache.set("main", sql, {"id": 2}, ["b"])
        assert await cache.get("main", sql, {"id": 1}) == ["a"]
        assert await cache.get("main", sql, {"id": 2}) == ["b"]

    @pytest.mark.asyncio
    async def test_ttl_applied(self, cache):
        # MemoryBackend игнорирует per-key TTL, но set/get должны работать
        await cache.set("main", "SELECT 1", result=[1], ttl=10)
        assert await cache.get("main", "SELECT 1") == [1]

    @pytest.mark.asyncio
    async def test_invalidate_table_removes_keys(self, cache):
        sql1 = "SELECT * FROM users WHERE id = :id"
        sql2 = "SELECT * FROM orders WHERE user_id = :uid"
        await cache.set("main", sql1, {"id": 1}, [{"id": 1}], tables=["users"])
        await cache.set("main", sql2, {"uid": 1}, [{"oid": 1}], tables=["orders"])

        assert await cache.get("main", sql1, {"id": 1}) is not None
        deleted = await cache.invalidate_table("main", "users")
        assert deleted == 1
        assert await cache.get("main", sql1, {"id": 1}) is None
        assert await cache.get("main", sql2, {"uid": 1}) is not None

    @pytest.mark.asyncio
    async def test_invalidate_table_noop_when_empty(self, cache):
        deleted = await cache.invalidate_table("main", "nonexistent")
        assert deleted == 0

    @pytest.mark.asyncio
    async def test_invalidate_profile_clears_all(self, cache):
        await cache.set("main", "SELECT 1", result=[1], tables=["t1"])
        await cache.set("main", "SELECT 2", result=[2], tables=["t2"])
        await cache.set("other", "SELECT 3", result=[3])

        await cache.invalidate_profile("main")
        assert await cache.get("main", "SELECT 1") is None
        assert await cache.get("main", "SELECT 2") is None
        assert await cache.get("other", "SELECT 3") is not None

    @pytest.mark.asyncio
    async def test_deserialize_corrupt_data_deletes_key(self, cache):
        key = cache._make_key("main", "SELECT 1", None)
        await cache._backend.set(key, b"not_valid_pickle")
        assert await cache.get("main", "SELECT 1") is None
        assert not await cache._backend.exists(key)

    @pytest.mark.asyncio
    async def test_profile_isolation(self, cache):
        await cache.set("main", "SELECT 1", result=[1])
        await cache.set("replica", "SELECT 1", result=[2])
        assert await cache.get("main", "SELECT 1") == [1]
        assert await cache.get("replica", "SELECT 1") == [2]


class TestPickleRuntimeGuard:
    """Sprint 3.3: ``PickleSerializer`` + non-MemoryBackend → RuntimeError.

    Pickle — RCE-vector для shared cache namespace (Redis/Memcached/KeyDB):
    любой writer в namespace может исполнить код при ``pickle.loads``.
    MemoryBackend — единственный trusted бэкенд (данные под контролем
    текущего процесса). Guard срабатывает в ``__init__`` QueryResultCache
    (fail-fast, до первого set/get).
    """

    @staticmethod
    def _fake_non_memory_backend() -> Any:
        """Минимальный CacheBackend-stub, не являющийся MemoryBackend."""

        class _FakeBackend(CacheBackend):  # type: ignore[misc]
            """Подделка shared-бэкенда (Redis/Memcached/KeyDB-семантика)."""

            async def get(self, key: str) -> bytes | None:
                return None

            async def set(self, key: str, value: bytes, ttl: int | None = None) -> None:
                return None

            async def delete(self, *keys: str) -> None:
                return None

            async def delete_pattern(self, pattern: str) -> None:
                return None

            async def exists(self, key: str) -> bool:
                return False

        return _FakeBackend()

    def test_pickle_with_memory_backend_allowed(self):
        """Pickle + MemoryBackend — допустимая комбинация."""
        backend = MemoryBackend(maxsize=10)
        cache = QueryResultCache(backend=backend, serializer=PickleSerializer())
        assert isinstance(cache._serializer, PickleSerializer)

    def test_pickle_with_non_memory_backend_rejected(self):
        """Pickle + shared-бэкенд → RuntimeError (fail-fast в __init__)."""
        backend = self._fake_non_memory_backend()
        with pytest.raises(RuntimeError) as exc_info:
            QueryResultCache(backend=backend, serializer=PickleSerializer())
        msg = str(exc_info.value)
        assert "PickleSerializer" in msg
        assert "RCE-vector" in msg or "RCE" in msg

    def test_pickle_with_non_memory_subclass_rejected(self):
        """Любой CacheBackend, не наследующий MemoryBackend → RuntimeError."""
        backend = self._fake_non_memory_backend()
        # Проверяем даже для подкласса, не наследующего MemoryBackend
        with pytest.raises(RuntimeError):
            QueryResultCache(backend=backend, serializer=PickleSerializer())

    @pytest.mark.asyncio
    async def test_orjson_with_non_memory_backend_allowed(self):
        """OrjsonSerializer + shared-бэкенд — guard не срабатывает."""
        backend = self._fake_non_memory_backend()
        cache = QueryResultCache(backend=backend, serializer=OrjsonSerializer())
        # set/get работают (бэкенд-fake возвращает None → get вернёт None)
        await cache.set("p", "SELECT 1", result=[1])
        assert await cache.get("p", "SELECT 1") is None

    @pytest.mark.asyncio
    async def test_json_with_non_memory_backend_allowed(self):
        """JsonSerializer + shared-бэкенд — guard не срабатывает."""
        backend = self._fake_non_memory_backend()
        cache = QueryResultCache(backend=backend, serializer=JsonSerializer())
        await cache.set("p", "SELECT 1", result={"rows": [1, 2]})
        assert await cache.get("p", "SELECT 1") is None

    def test_default_serializer_with_non_memory_backend_allowed(self):
        """Default (orjson) + shared-бэкенд — guard не срабатывает."""
        backend = self._fake_non_memory_backend()
        cache = QueryResultCache(backend=backend)
        assert isinstance(cache._serializer, OrjsonSerializer)

    def test_memory_backend_subclass_pickle_allowed(self):
        """Подкласс MemoryBackend наследует 'trusted' статус."""

        class _TrustedMemoryLike(MemoryBackend):
            """Подкласс MemoryBackend — данные остаются in-process."""

        backend = _TrustedMemoryLike(maxsize=10)
        cache = QueryResultCache(backend=backend, serializer=PickleSerializer())
        assert isinstance(cache._serializer, PickleSerializer)
