"""Unit-тесты httpx_cache_adapter (Sprint 9 K2 W5)."""

from __future__ import annotations

from src.backend.infrastructure.clients.transport.httpx_cache_adapter import (
    build_cache_transport,
    is_hishel_available,
)


class _FakeTransport:
    """Минимальный fake httpx.AsyncBaseTransport substitute."""


def test_is_hishel_available_returns_bool() -> None:
    assert isinstance(is_hishel_available(), bool)


def test_build_cache_transport_returns_none_when_hishel_missing(
    monkeypatch,
) -> None:
    """Когда hishel недоступен, build_cache_transport возвращает None."""
    import builtins

    original_import = builtins.__import__

    def _block_hishel(name, *args, **kwargs):
        if name == "hishel" or name.startswith("hishel."):
            raise ImportError("hishel unavailable in test")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _block_hishel)
    result = build_cache_transport(_FakeTransport())
    assert result is None


def test_build_cache_transport_with_custom_methods() -> None:
    """Проверяет что custom cacheable_methods/codes пробрасываются.

    Если hishel установлен, transport возвращается; иначе None.
    Этот тест проверяет, что вызов не падает с TypeError.
    """
    result = build_cache_transport(
        _FakeTransport(),
        cacheable_methods=("GET",),
        cacheable_status_codes=(200,),
        allow_heuristics=False,
        allow_stale=True,
    )
    # Either None (hishel absent) or hishel.AsyncCacheTransport instance
    assert result is None or hasattr(result, "handle_async_request")
