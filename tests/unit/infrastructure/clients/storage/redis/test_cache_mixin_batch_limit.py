"""S178 #1: тесты batch limit enforcement в CacheMixin.bulk_get/bulk_set.

Проверяет:
- bulk_get с ``len(keys) <= _MAX_BATCH_LIMIT`` → execute() вызывается
- bulk_get с ``len(keys) > _MAX_BATCH_LIMIT`` → ValueError ДО execute
- bulk_set — то же для items
- Empty list/dict → no-op без execute

Tests используют minimal subclass CacheMixin с подменённым ``execute`` —
НЕ поднимают реальный Redis.
"""


from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.backend.infrastructure.clients.storage.redis import cache_mixin as cm_mod


class _StubCache(cm_mod.CacheMixin):
    """Minimal CacheMixin subclass с подменённым execute().

    Не требует реального Redis — execute() это AsyncMock, проверяющий
    args и возвращающий предопределённый результат.
    """

    def __init__(self, execute_return: Any = None) -> None:
        self._execute_mock = AsyncMock(return_value=execute_return)
        self.execute_calls: list[tuple[str, Any]] = []

    async def execute(self, kind: str, operation: Any) -> Any:
        """Spy wrapper — records calls + returns predefined result."""
        self.execute_calls.append((kind, operation))
        return await self._execute_mock(kind, operation)


class TestBulkGetBatchLimit:
    """S178 #1: bulk_get batch limit (default 1000)."""

    @pytest.mark.asyncio
    async def test_empty_keys_no_op(self) -> None:
        """Пустой keys → return [] без execute."""
        stub = _StubCache()
        result = await stub.bulk_get([])
        assert result == []
        assert stub.execute_calls == []

    @pytest.mark.asyncio
    async def test_keys_below_limit_calls_execute(self) -> None:
        """keys < limit → execute() вызывается."""
        stub = _StubCache(execute_return=[b"v1", b"v2"])
        result = await stub.bulk_get(["k1", "k2"])
        assert result == [b"v1", b"v2"]
        assert len(stub.execute_calls) == 1
        kind, _op = stub.execute_calls[0]
        assert kind == "cache"

    @pytest.mark.asyncio
    async def test_keys_at_limit_calls_execute(self) -> None:
        """keys == limit (1000) → execute() вызывается."""
        stub = _StubCache(execute_return=[])
        keys = [f"k{i}" for i in range(cm_mod._MAX_BATCH_LIMIT)]
        result = await stub.bulk_get(keys)
        assert result == []
        assert len(stub.execute_calls) == 1

    @pytest.mark.asyncio
    async def test_keys_above_limit_raises_value_error(self) -> None:
        """keys > limit (1001) → ValueError ДО execute."""
        stub = _StubCache()
        keys = [f"k{i}" for i in range(cm_mod._MAX_BATCH_LIMIT + 1)]
        with pytest.raises(ValueError, match=r"batch size \d+ exceeds limit"):
            await stub.bulk_get(keys)
        # execute НЕ вызван — fail-fast.
        assert stub.execute_calls == []

    @pytest.mark.asyncio
    async def test_keys_above_limit_includes_count_in_error(self) -> None:
        """Error message содержит batch size и limit."""
        stub = _StubCache()
        keys = [f"k{i}" for i in range(cm_mod._MAX_BATCH_LIMIT + 100)]
        with pytest.raises(ValueError) as exc_info:
            await stub.bulk_get(keys)
        error_msg = str(exc_info.value)
        assert str(cm_mod._MAX_BATCH_LIMIT + 100) in error_msg
        assert str(cm_mod._MAX_BATCH_LIMIT) in error_msg


class TestBulkSetBatchLimit:
    """S178 #1: bulk_set batch limit (default 1000)."""

    @pytest.mark.asyncio
    async def test_empty_items_no_op(self) -> None:
        """Пустой items → no-op без execute."""
        stub = _StubCache()
        await stub.bulk_set({})
        assert stub.execute_calls == []

    @pytest.mark.asyncio
    async def test_items_below_limit_calls_execute(self) -> None:
        """items < limit → execute() вызывается."""
        stub = _StubCache(execute_return=None)
        await stub.bulk_set({"k1": "v1", "k2": "v2"})
        assert len(stub.execute_calls) == 1
        kind, _op = stub.execute_calls[0]
        assert kind == "cache"

    @pytest.mark.asyncio
    async def test_items_at_limit_calls_execute(self) -> None:
        """items == limit (1000) → execute() вызывается."""
        stub = _StubCache(execute_return=None)
        items = {f"k{i}": f"v{i}" for i in range(cm_mod._MAX_BATCH_LIMIT)}
        await stub.bulk_set(items)
        assert len(stub.execute_calls) == 1

    @pytest.mark.asyncio
    async def test_items_above_limit_raises_value_error(self) -> None:
        """items > limit (1001) → ValueError ДО execute."""
        stub = _StubCache()
        items = {f"k{i}": f"v{i}" for i in range(cm_mod._MAX_BATCH_LIMIT + 1)}
        with pytest.raises(ValueError, match=r"batch size \d+ exceeds limit"):
            await stub.bulk_set(items)
        assert stub.execute_calls == []

    @pytest.mark.asyncio
    async def test_items_with_expire_above_limit(self) -> None:
        """bulk_set с expire тоже проверяет limit."""
        stub = _StubCache()
        items = {f"k{i}": f"v{i}" for i in range(cm_mod._MAX_BATCH_LIMIT + 1)}
        with pytest.raises(ValueError, match=r"batch size \d+ exceeds limit"):
            await stub.bulk_set(items, expire=60)


class TestBatchLimitConstant:
    """S178 #1: _MAX_BATCH_LIMIT constant."""

    def test_max_batch_limit_is_1000(self) -> None:
        """Sprint 178 константа = 1000."""
        assert cm_mod._MAX_BATCH_LIMIT == 1000

    def test_max_batch_limit_is_positive(self) -> None:
        """Limit > 0 (защита от off-by-one)."""
        assert cm_mod._MAX_BATCH_LIMIT > 0
