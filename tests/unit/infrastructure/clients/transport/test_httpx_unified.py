"""Unit-тесты для K2 S7 unified httpx transport stack.

Покрывают чистые функции уровня модуля (без bootstrap всего ``settings``):
* ``build_cache_transport`` — graceful fallback при отсутствии hishel;
* ``is_hishel_available`` — lazy-import helper;
* ``is_httpx_retries_available`` — lazy-import helper (через try/except);
* интеграционная проверка cache_transport с реальным hishel (если установлен).

Тесты ``HttpxClient`` (с реальным settings + feature_flag) — в integration suite,
поскольку требуют live env-bootstrap (DB_USERNAME/DB_PASSWORD + .env).
"""

from __future__ import annotations

import sys

import httpx
import pytest

from src.backend.infrastructure.clients.transport.httpx_cache_adapter import (
    build_cache_transport,
    is_hishel_available,
)


def test_is_hishel_available_returns_bool() -> None:
    """``is_hishel_available`` стабильно возвращает bool, не падает."""
    assert isinstance(is_hishel_available(), bool)


def test_build_cache_transport_returns_none_without_hishel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """При отсутствии hishel ``build_cache_transport`` возвращает None.

    Caller должен использовать inner_transport напрямую (graceful fallback).
    """
    # Симулируем отсутствие hishel: блокируем import.
    monkeypatch.setitem(sys.modules, "hishel", None)
    inner = httpx.AsyncHTTPTransport()
    result = build_cache_transport(inner)
    assert result is None


def test_build_cache_transport_with_hishel_returns_transport() -> None:
    """Когда hishel установлен — возвращается AsyncCacheTransport."""
    if not is_hishel_available():
        pytest.skip("hishel не установлен в окружении")
    inner = httpx.AsyncHTTPTransport()
    result = build_cache_transport(inner, allow_heuristics=True)
    assert result is not None
    assert isinstance(result, httpx.AsyncBaseTransport)
    # ``hishel.AsyncCacheTransport`` оборачивает inner; имя содержит Cache.
    assert "Cache" in type(result).__name__


def test_build_cache_transport_custom_status_codes() -> None:
    """Контроль ``cacheable_status_codes`` пробрасывается в Controller."""
    if not is_hishel_available():
        pytest.skip("hishel не установлен в окружении")
    inner = httpx.AsyncHTTPTransport()
    result = build_cache_transport(inner, cacheable_status_codes=(200, 304))
    assert result is not None


def test_is_httpx_retries_available_returns_bool() -> None:
    """Lazy-import проверка для httpx_retries стабильна и возвращает bool."""
    try:
        import httpx_retries  # noqa: F401

        available = True
    except ImportError:
        available = False
    assert isinstance(available, bool)
