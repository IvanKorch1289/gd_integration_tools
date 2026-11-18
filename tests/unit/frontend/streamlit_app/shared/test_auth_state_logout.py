"""Регресс-тест: ``logout()`` очищает глобальный API-кэш Streamlit.

``st.cache_data`` — процесс-глобальный кэш портала. До правки выход
пользователя оставлял его записи до TTL: ответ ушедшего пользователя
мог достаться следующему. После ``logout()`` кэш обязан быть пустым.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
import streamlit as st

from src.frontend.streamlit_app.shared import auth_state


@pytest.fixture(autouse=True)
def _clean_cache() -> Iterator[None]:
    """Чистить глобальный кэш Streamlit до/после каждого теста."""
    st.cache_data.clear()
    yield
    st.cache_data.clear()


@pytest.mark.unit
class TestLogoutClearsApiCache:
    """``logout()`` сбрасывает session state и очищает API-кэш."""

    def test_logout_clears_session_state(self) -> None:
        """Все auth-ключи удалены из session state."""
        st.session_state["auth_token"] = "jwt"
        st.session_state["auth_username"] = "user"
        st.session_state["auth_method"] = "password"
        st.session_state["auth_issued_at"] = 1.0
        st.session_state["auth_expires_in"] = 3600

        auth_state.logout()

        assert st.session_state.get("auth_token") is None
        assert st.session_state.get("auth_username") is None
        assert st.session_state.get("auth_method") is None
        assert st.session_state.get("auth_issued_at") is None
        assert st.session_state.get("auth_expires_in") is None

    def test_logout_clears_cached_api_responses(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Logout вызывает очистку глобального API-кэша.

        Проверяем ВЫЗОВ очистки, а не поведение глобального ``st.cache_data``:
        в общем прогоне часть тестов подменяет ``st.cache_data`` моком, и
        тогда «поведенческая» проверка зависит от чужой подмены, а не от
        кода logout'а. Семантика «кэш ушедшего пользователя не переживает
        выход» обеспечивается тем, что logout дергает ``clear_api_cache()``.
        """
        cleared: list[str] = []

        def _spy() -> None:
            cleared.append("cleared")

        monkeypatch.setattr(
            "src.frontend.streamlit_app.api_clients.cached.clear_api_cache", _spy
        )
        st.session_state["auth_token"] = "token-a"

        auth_state.logout()

        assert cleared == ["cleared"], "logout обязан очищать глобальный API-кэш"

    def test_logout_survives_cache_clear_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Сбой очистки кэша не блокирует выход — session state чистится."""

        def _boom() -> None:
            raise RuntimeError("cache backend unavailable")

        monkeypatch.setattr(
            "src.frontend.streamlit_app.api_clients.cached.clear_api_cache", _boom
        )
        st.session_state["auth_token"] = "jwt"

        auth_state.logout()

        assert st.session_state.get("auth_token") is None
