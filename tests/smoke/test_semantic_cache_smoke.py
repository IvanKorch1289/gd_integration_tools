"""S36 w1 — Smoke test: SemanticCache (AI cache layer).

Проверяет детерминированные части SemanticCache:
- конструирование с дефолтами;
- генерация ключей (sha256-based exact-match);
- уникальность ключей для разных запросов;
- стабильность ключей для одного запроса.

Сетевые операции (Redis get/set) проверяются отдельно
в unit-тестах с fakeredis.
"""

# ruff: noqa: S101

from __future__ import annotations

from src.backend.infrastructure.ai.semantic_cache import SemanticCache


def test_semantic_cache_default_construction() -> None:
    """SemanticCache() с дефолтами — prefix='ai-cache:', threshold=0.95, ttl=3600."""
    cache = SemanticCache()

    assert cache.prefix == "ai-cache:"
    assert cache.threshold == 0.95
    assert cache.ttl_seconds == 3600


def test_semantic_cache_custom_construction() -> None:
    """SemanticCache с custom prefix/threshold/ttl сохраняет параметры."""
    cache = SemanticCache(prefix="smoke:", threshold=0.80, ttl_seconds=60)

    assert cache.prefix == "smoke:"
    assert cache.threshold == 0.80
    assert cache.ttl_seconds == 60


def test_semantic_cache_key_is_deterministic() -> None:
    """_exact_key(q) → один и тот же ключ для одного запроса."""
    cache = SemanticCache()

    key1 = cache._exact_key("hello world")  # noqa: SLF001
    key2 = cache._exact_key("hello world")  # noqa: SLF001

    assert key1 == key2
    assert key1.startswith(cache.prefix)


def test_semantic_cache_key_distinct_per_query() -> None:
    """_exact_key: разные запросы → разные ключи."""
    cache = SemanticCache()

    key_a = cache._exact_key("query A")  # noqa: SLF001
    key_b = cache._exact_key("query B")  # noqa: SLF001

    assert key_a != key_b


def test_semantic_cache_key_uses_sha256() -> None:
    """_exact_key: ключ включает sha256-хеш (64 hex chars после prefix)."""
    cache = SemanticCache()

    key = cache._exact_key("anything")  # noqa: SLF001
    hex_part = key.removeprefix(cache.prefix)

    assert len(hex_part) == 64
    assert all(c in "0123456789abcdef" for c in hex_part)
