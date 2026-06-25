"""Auth session state — Streamlit session helpers для login/logout.

S169: Управление JWT token в ``st.session_state``.
``api_client.set_token(token)`` вызывается при логине для распространения
JWT на все доменные клиенты.
"""

from __future__ import annotations

import time
from typing import Any, Literal

import streamlit as st

from src.frontend.streamlit_app.api_clients.auth import AuthClient

__all__ = (
    "is_authenticated",
    "get_current_token",
    "get_current_username",
    "get_current_auth_method",
    "login",
    "logout",
    "require_auth",
)


_SESSION_KEY_TOKEN = "auth_token"  # noqa: S105 — это dict key, не пароль
_SESSION_KEY_USERNAME = "auth_username"
_SESSION_KEY_METHOD = "auth_method"
_SESSION_KEY_ISSUED_AT = "auth_issued_at"
_SESSION_KEY_EXPIRES_IN = "auth_expires_in"


def _client() -> AuthClient:
    """Получить singleton AuthClient из session state (или создать)."""
    if "auth_client" not in st.session_state:
        st.session_state["auth_client"] = AuthClient()
    return st.session_state["auth_client"]  # type: ignore[no-any-return]


def is_authenticated() -> bool:
    """True если в session state есть валидный (не просроченный) JWT token."""
    token = st.session_state.get(_SESSION_KEY_TOKEN)
    if not token:
        return False
    issued_at = st.session_state.get(_SESSION_KEY_ISSUED_AT, 0)
    expires_in = st.session_state.get(_SESSION_KEY_EXPIRES_IN, 3600)
    # 30s skew на clock-skew и latency
    if time.time() > issued_at + expires_in - 30:
        return False
    return True


def get_current_token() -> str | None:
    """Получить текущий JWT token (для ``api_client.set_token``)."""
    return st.session_state.get(_SESSION_KEY_TOKEN)


def get_current_username() -> str | None:
    return st.session_state.get(_SESSION_KEY_USERNAME)


def get_current_auth_method() -> str | None:
    return st.session_state.get(_SESSION_KEY_METHOD)


def login(
    *, username: str, password: str, method: Literal["password", "ldap"] = "password"
) -> None:
    """Логин: вызывает /auth/login, сохраняет token в session state.

    Args:
        username: Имя пользователя.
        password: Пароль.
        method: ``"password"`` или ``"ldap"`` (S58 W6d).
    """
    client = _client()
    response = client.login(method=method, username=username, password=password)
    now = time.time()
    st.session_state[_SESSION_KEY_TOKEN] = response.access_token
    st.session_state[_SESSION_KEY_USERNAME] = response.username
    st.session_state[_SESSION_KEY_METHOD] = response.auth_method
    st.session_state[_SESSION_KEY_ISSUED_AT] = now
    st.session_state[_SESSION_KEY_EXPIRES_IN] = response.expires_in


def logout() -> None:
    """Логаут: очищает session state и token в api_clients."""
    for key in (
        _SESSION_KEY_TOKEN,
        _SESSION_KEY_USERNAME,
        _SESSION_KEY_METHOD,
        _SESSION_KEY_ISSUED_AT,
        _SESSION_KEY_EXPIRES_IN,
    ):
        st.session_state.pop(key, None)


def require_auth() -> bool:
    """Auth-gate: вызывать в начале ``app.py`` / страниц.

    Returns True если пользователь аутентифицирован (продолжаем).
    Returns False если не аутентифицирован (login form уже показан).
    """
    return is_authenticated()


def apply_token_to_clients(api_clients: list[Any]) -> None:
    """Применить текущий token ко всем API-клиентам.

    Вызывать после ``login()`` чтобы все доменные клиенты начали
    использовать Bearer auth.
    """
    token = get_current_token()
    if not token:
        return
    for client in api_clients:
        if hasattr(client, "set_token"):
            client.set_token(token)
