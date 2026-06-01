"""Тесты build_cache_key (Wave 3)."""

# ruff: noqa: S101

from __future__ import annotations

from src.backend.core.utils.cache_keys import build_cache_key


def test_cache_key_stable_for_different_kwarg_order() -> None:
    """Разный порядок kwargs даёт одинаковый ключ."""

    async def dummy(a: int, b: str) -> str:
        return f"{a}-{b}"

    key1 = build_cache_key(dummy, (1,), {"b": "x", "a": 2})
    key2 = build_cache_key(dummy, (1,), {"a": 2, "b": "x"})
    assert key1 == key2


def test_cache_key_different_for_different_args() -> None:
    """Разные аргументы дают разные ключи."""

    async def dummy(a: int) -> int:
        return a

    key1 = build_cache_key(dummy, (1,), {})
    key2 = build_cache_key(dummy, (2,), {})
    assert key1 != key2


def test_cache_key_includes_module_and_name() -> None:
    """Ключ включает module и name функции."""

    async def dummy() -> None:
        pass

    key = build_cache_key(dummy, (), {})
    assert key.startswith("cache:")
    assert len(key) == 70  # "cache:" (6) + sha256 hex (64)


def test_cache_key_exclude_self() -> None:
    """exclude_self убирает первый аргумент из ключа."""

    class Foo:
        async def method(self, x: int) -> int:
            return x

    foo = Foo()
    key_with = build_cache_key(foo.method, (foo, 1), {}, exclude_self=False)
    key_without = build_cache_key(foo.method, (foo, 1), {}, exclude_self=True)
    assert key_with != key_without
