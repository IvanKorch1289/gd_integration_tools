# ruff: noqa: S105 — false positive (config field name, not a password)
"""Auth session state — Streamlit session helpers для login/logout.

S169: Управление JWT token в ``st.session_state``. ``BaseAPIClient`` читает
его при сборке заголовков и передаёт всем доменным клиентам текущей сессии.
"""

from __future__ import annotations

import hashlib
import logging
import time
from typing import Any, Literal

import streamlit as st

from src.frontend.streamlit_app.api_clients.auth import AuthClient

__all__ = (
    "get_auth_cache_scope",
    "get_current_auth_method",
    "get_current_token",
    "get_current_username",
    "is_authenticated",
    "login",
    "logout",
    "require_auth",
)


_SESSION_KEY_TOKEN = "auth_token"
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


def get_auth_cache_scope() -> str:
    """Ключ области кэша для текущей сессии.

    ``st.cache_data`` — процесс-глобальный кэш (данные делятся между всеми
    пользователями портала). Если scope не входит в ключ кэша, ответ,
    полученный для одного пользователя/тенанта, отдаётся другому.

    Scope = sha256 от текущего JWT. Сам токен в ключ не попадает — в кэш
    уходит только необратимый digest. Для анонимной сессии — ``"anonymous"``.

    Returns:
        Строковый scope для включения в ключ кэша.

    """
    session_state = getattr(st, "session_state", None)
    if session_state is None:
        # Вне runtime Streamlit (bare-mode / тестовые моки) — общая область.
        return "anonymous"
    token = session_state.get(_SESSION_KEY_TOKEN)
    if not isinstance(token, str) or not token:
        return "anonymous"
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def get_current_username() -> str | None:
    """Метод get_current_username (см. signature)."""
    return st.session_state.get(_SESSION_KEY_USERNAME)


def get_current_auth_method() -> str | None:
    """Метод get_current_auth_method (см. signature)."""
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


def _clear_api_cache() -> None:
    """Очистить глобальный кэш API-ответов Streamlit (best-effort).

    ``st.cache_data`` — процесс-глобальный кэш портала. Без очистки
    ответы ушедшего пользователя остаются в нём до TTL.

    Очистка best-effort: сбой очистки кэша не должен блокировать выход —
    session state к этому моменту уже очищен, а кэш истечёт по TTL.
    """
    try:
        # Lazy-import: api_clients тянет hooks.cache → auth_state.
        from src.frontend.streamlit_app.api_clients.cached import clear_api_cache

        clear_api_cache()
    except Exception as exc:  # noqa: BLE001 — logout не должен падать из-за кэша
        logging.getLogger(__name__).error(
            "auth_state.logout_cache_clear_failed: %s", exc
        )


def logout() -> None:
    """Логаут: очищает session state, token в api_clients и API-кэш.

    Кэш API-клиента обязателен к очистке: ``st.cache_data`` —
    процесс-глобальный кэш, поэтому записи ушедшего пользователя
    иначе оставались бы в нём до TTL и могли достаться следующему.
    """
    for key in (
        _SESSION_KEY_TOKEN,
        _SESSION_KEY_USERNAME,
        _SESSION_KEY_METHOD,
        _SESSION_KEY_ISSUED_AT,
        _SESSION_KEY_EXPIRES_IN,
    ):
        st.session_state.pop(key, None)
    _clear_api_cache()


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
