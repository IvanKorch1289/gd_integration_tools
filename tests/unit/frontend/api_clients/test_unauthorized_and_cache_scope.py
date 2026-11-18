"""Регресс-тесты: 401-обработка и изоляция кэша между сессиями.

Найдено в ходе фронт-аудита (S174):

1. ``BaseAPIClient._request`` поднимал 401 как голый ``PermissionError``.
   ``PermissionError`` не является подклассом ``httpx.HTTPError``, поэтому
   ``except httpx.HTTPError`` в страницах 401 не ловил — пользователь видел
   traceback вместо сообщения. Исправлено: ``UnauthorizedError`` наследует
   оба класса.

2. ``st.cache_data`` — процесс-глобальный кэш (данные делятся между всеми
   пользователями портала). Ключи кэша не содержали scope пользователя,
   поэтому ответ, полученный для одного пользователя/тенанта, отдавался
   другому. Исправлено: ``user_scoped_cache_data`` добавляет digest текущего
   JWT в ключ кэша.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import streamlit as st

from src.frontend.streamlit_app.api_clients.base import (
    CLIENT_SAFE_DEFAULT_ERRORS,
    BaseAPIClient,
    UnauthorizedError,
)
from src.frontend.streamlit_app.hooks.cache import user_scoped_cache_data
from src.frontend.streamlit_app.shared.auth_state import get_auth_cache_scope

#: Настоящий streamlit, захваченный на этапе сбора тестов. Другие фронт-тесты
#: подменяют ``sys.modules['streamlit']`` моками — без восстановления здесь
#: результат зависел бы от порядка запуска.
_REAL_STREAMLIT = st


@pytest.fixture(autouse=True)
def _real_streamlit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Гарантировать настоящий streamlit на время теста."""
    monkeypatch.setitem(sys.modules, "streamlit", _REAL_STREAMLIT)


@pytest.fixture(autouse=True)
def _clear_cache() -> Iterator[None]:
    """Чистить глобальный кэш Streamlit до/после каждого теста."""
    st.cache_data.clear()
    yield
    st.cache_data.clear()


def _response_401() -> httpx.Response:
    """Ответ backend'а «401 Unauthorized»."""
    request = httpx.Request("GET", "http://localhost:8000/api/v1/admin/routes")
    return httpx.Response(401, request=request)


@pytest.mark.unit
class TestUnauthorizedError:
    """401 должен ловиться и как PermissionError, и как httpx.HTTPError."""

    def test_inherits_both_contracts(self) -> None:
        """UnauthorizedError — потомок PermissionError и httpx.HTTPError."""
        exc = UnauthorizedError(
            "Unauthorized: /api/v1/admin/routes",
            request=_response_401().request,
            response=_response_401(),
        )
        assert isinstance(exc, PermissionError)
        assert isinstance(exc, httpx.HTTPError)
        assert isinstance(exc, httpx.HTTPStatusError)
        assert "Unauthorized" in str(exc)

    def test_401_raises_unauthorized_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Ответ 401 поднимает UnauthorizedError, а не голый PermissionError."""
        response = _response_401()

        def _request(self: Any, *args: Any, **kwargs: Any) -> httpx.Response:
            return response

        monkeypatch.setattr(httpx.Client, "request", _request)
        client = BaseAPIClient(base_url="http://localhost:8000")
        with pytest.raises(UnauthorizedError):
            client.get("/api/v1/admin/routes")

    def test_client_safe_default_errors_covers_401(self) -> None:
        """CLIENT_SAFE_DEFAULT_ERRORS включает 401 — клиент не роняет UI."""
        assert UnauthorizedError in CLIENT_SAFE_DEFAULT_ERRORS
        assert httpx.HTTPError in CLIENT_SAFE_DEFAULT_ERRORS


@pytest.mark.unit
class TestAuthCacheScope:
    """Scope кэша разделяет сессии пользователей."""

    def test_anonymous_without_token(self) -> None:
        """Без токена scope = 'anonymous'."""
        st.session_state.pop("auth_token", None)
        assert get_auth_cache_scope() == "anonymous"

    def test_scope_is_stable_per_token(self) -> None:
        """Один и тот же токен → один и тот же scope."""
        st.session_state["auth_token"] = "token-a"
        first = get_auth_cache_scope()
        assert first == get_auth_cache_scope()
        assert first != "anonymous"

    def test_scope_differs_per_token(self) -> None:
        """Разные токены → разные scope (нет утечки между пользователями)."""
        st.session_state["auth_token"] = "token-a"
        scope_a = get_auth_cache_scope()
        st.session_state["auth_token"] = "token-b"
        scope_b = get_auth_cache_scope()
        assert scope_a != scope_b

    def test_scope_does_not_expose_raw_token(self) -> None:
        """В scope нет сырого JWT — только необратимый digest."""
        st.session_state["auth_token"] = "super-secret-jwt-value"
        scope = get_auth_cache_scope()
        assert "super-secret-jwt-value" not in scope


@pytest.mark.unit
class TestUserScopedCacheData:
    """user_scoped_cache_data разделяет кэш по scope."""

    def test_different_scopes_do_not_share_entries(self) -> None:
        """Разные пользователи → разные записи кэша (данные не утекают)."""
        calls: list[int] = []

        @user_scoped_cache_data(ttl=60)
        def _fetch(value: int) -> int:
            calls.append(value)
            return len(calls)

        st.session_state["auth_token"] = "token-a"
        first = _fetch(1)
        st.session_state["auth_token"] = "token-b"
        second = _fetch(1)
        st.session_state["auth_token"] = "token-a"
        third = _fetch(1)

        assert first == 1
        assert second == 2, "второй пользователь обязан получить свой ответ"
        assert third == 1, "первый пользователь обязан получить свой кэш"
        assert calls == [1, 1]

    def test_same_scope_reuses_cache(self) -> None:
        """Один пользователь — кэш работает (не сломан scope'ом)."""
        calls: list[int] = []

        @user_scoped_cache_data(ttl=60)
        def _fetch(value: int) -> int:
            calls.append(value)
            return len(calls)

        st.session_state["auth_token"] = "token-a"
        assert _fetch(7) == 1
        assert _fetch(7) == 1
        assert calls == [7]
