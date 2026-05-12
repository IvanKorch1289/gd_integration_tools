"""Тесты TierRouter: L1→L2→L3 + write-through promotion (Sprint 3 W1 К4 Шаг 2).

Покрывает 5 базовых сценариев:
    1. L1 hit — без обращения к нижним tier'ам.
    2. L2 hit → promote в L1.
    3. L3 hit → promote в L1 и L2.
    4. Miss во всех tier'ах → ``None``.
    5. set() — write-through в L1 + L2; L3 только при ``semantic_key``.
"""

from __future__ import annotations

import pytest

from src.backend.infrastructure.ai.semantic_cache import TierRouter
from src.backend.infrastructure.cache.lru_cache import LruMemoryCache


class _FakeBackend:
    """Простой async backend для L2/L3 без реального Redis/Qdrant."""

    def __init__(self) -> None:
        self.store: dict[str, object] = {}
        self.get_calls = 0
        self.set_calls = 0

    async def get(self, key: str) -> object | None:
        self.get_calls += 1
        return self.store.get(key)

    async def set(self, key: str, value: object) -> None:
        self.set_calls += 1
        self.store[key] = value

    async def delete(self, *keys: str) -> None:
        for key in keys:
            self.store.pop(key, None)


@pytest.mark.asyncio
async def test_l1_hit_returns_value_without_lower_tier_lookup() -> None:
    """L1 hit → возврат значения; L2/L3 не опрашиваются."""
    l2 = _FakeBackend()
    l3 = _FakeBackend()
    router = TierRouter(l1=LruMemoryCache(scope="tr-l1-hit"), l2=l2, l3=l3)
    # Через router.set() заполним L1.
    await router.set("k", "value-from-l1")
    # Сбросим счётчики L2 (set уже инкрементировал) — нас интересует только get.
    l2.get_calls = 0
    l3.get_calls = 0
    result = await router.get("k")
    assert result == "value-from-l1"
    assert l2.get_calls == 0
    assert l3.get_calls == 0


@pytest.mark.asyncio
async def test_l2_hit_promotes_to_l1() -> None:
    """L2 hit → значение возвращено; на повторный get hit уже в L1."""
    l2 = _FakeBackend()
    l3 = _FakeBackend()
    l1 = LruMemoryCache(scope="tr-l2-hit")
    router = TierRouter(l1=l1, l2=l2, l3=l3)
    # Кладём напрямую в L2, минуя router.set.
    l2.store["k"] = "value-from-l2"

    result1 = await router.get("k")
    assert result1 == "value-from-l2"
    # После promotion — L1 содержит значение.
    assert await l1.get("k") == "value-from-l2"
    # Повторный get не обращается к L2.
    l2_get_before = l2.get_calls
    result2 = await router.get("k")
    assert result2 == "value-from-l2"
    assert l2.get_calls == l2_get_before


@pytest.mark.asyncio
async def test_l3_hit_promotes_to_l1_and_l2() -> None:
    """L3 hit → promotion в L1 и L2."""
    l2 = _FakeBackend()
    l3 = _FakeBackend()
    l1 = LruMemoryCache(scope="tr-l3-hit")
    router = TierRouter(l1=l1, l2=l2, l3=l3)
    l3.store["k"] = "value-from-l3"

    result = await router.get("k")
    assert result == "value-from-l3"
    # Promotion проверяется через прямой доступ к backend'ам.
    assert await l1.get("k") == "value-from-l3"
    assert l2.store["k"] == "value-from-l3"


@pytest.mark.asyncio
async def test_miss_all_tiers_returns_none() -> None:
    """Все tier'ы miss → router возвращает None."""
    l2 = _FakeBackend()
    l3 = _FakeBackend()
    router = TierRouter(l1=LruMemoryCache(scope="tr-miss"), l2=l2, l3=l3)
    result = await router.get("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_set_write_through_l1_l2_only_l3_on_semantic_key() -> None:
    """set() пишет в L1+L2 безусловно; L3 только при semantic_key."""
    l2 = _FakeBackend()
    l3 = _FakeBackend()
    l1 = LruMemoryCache(scope="tr-set")
    router = TierRouter(l1=l1, l2=l2, l3=l3)

    await router.set("k1", "v1")
    assert await l1.get("k1") == "v1"
    assert l2.store["k1"] == "v1"
    assert "k1" not in l3.store

    await router.set("k2", "v2", semantic_key="raw-query-2")
    assert l2.store["k2"] == "v2"
    assert l3.store["raw-query-2"] == "v2"


@pytest.mark.asyncio
async def test_invalidate_clears_all_tiers() -> None:
    """invalidate(*keys) удаляет ключи во всех включённых tier'ах."""
    l2 = _FakeBackend()
    l3 = _FakeBackend()
    l1 = LruMemoryCache(scope="tr-inv")
    router = TierRouter(l1=l1, l2=l2, l3=l3)
    await router.set(
        "k", "v", semantic_key="k"
    )  # semantic_key=k чтобы L3 заполнился под "k"

    await router.invalidate("k")
    assert await l1.get("k") is None
    assert "k" not in l2.store
    assert "k" not in l3.store


@pytest.mark.asyncio
async def test_router_without_l2_l3_works_as_l1_only() -> None:
    """L2/L3 = None → router деградирует до L1-only без ошибок."""
    router = TierRouter(l1=LruMemoryCache(scope="tr-l1-only"))
    await router.set("k", "v")
    assert await router.get("k") == "v"
    assert await router.get("missing") is None
