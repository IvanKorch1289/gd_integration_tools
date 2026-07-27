"""Login page — S169.

Auth gate: пользователь видит эту страницу до успешного login.
После login — редирект на ``00_Вход`` (эту же страницу, либо home).

Backend endpoints:
* ``GET /auth/methods`` — список available methods.
* ``POST /auth/login`` — аутентификация.

Streamlit auto-discovers ``00_*.py`` файлы в ``pages/`` и сортирует
по имени. Префикс ``00_`` ставим выше Home (тоже ``00_``), добавляем
``_Login`` суффикс чтобы сортировка шла первой.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, TypedDict

import httpx
import streamlit as st

from src.frontend.streamlit_app.api_clients.auth import AuthClient
from src.frontend.streamlit_app.shared import auth_state

LoginMethod = Literal["password", "ldap"]


class _AuthMethodsInfo(TypedDict):
    """Validated auth response fields consumed by the login UI."""

    methods: list[LoginMethod]
    deprecations: dict[str, str]


_LOGIN_METHOD_LABELS: dict[LoginMethod, str] = {
    "password": "Логин / пароль",
    "ldap": "LDAP / AD",
}


def _default_auth_methods() -> _AuthMethodsInfo:
    return {"methods": ["password"], "deprecations": {}}


def _normalize_auth_methods(payload: object) -> _AuthMethodsInfo:
    """Validate the untrusted API mapping before the UI accesses its values."""
    if not isinstance(payload, Mapping):
        st.warning(
            "Backend вернул некорректный список auth-методов. "
            "Используется безопасный fallback: password."
        )
        return _default_auth_methods()

    raw_methods = payload.get("methods")
    if not isinstance(raw_methods, list):
        st.warning(
            "Backend вернул некорректное поле methods. "
            "Используется безопасный fallback: password."
        )
        return _default_auth_methods()

    methods: list[LoginMethod] = []
    for method in raw_methods:
        if method == "password":
            methods.append("password")
        elif method == "ldap":
            methods.append("ldap")

    if not methods:
        st.warning(
            "Backend не вернул поддерживаемых auth-методов. "
            "Используется безопасный fallback: password."
        )
        return _default_auth_methods()

    deprecations: dict[str, str] = {}
    raw_deprecations = payload.get("deprecations")
    if isinstance(raw_deprecations, Mapping):
        for method in methods:
            note = raw_deprecations.get(method)
            if isinstance(note, str):
                deprecations[method] = note
    elif raw_deprecations is not None:
        st.warning("Backend вернул некорректные deprecations; поле проигнорировано.")

    return {"methods": methods, "deprecations": deprecations}


def _fetch_methods(client: AuthClient) -> _AuthMethodsInfo:
    """``GET /auth/methods`` с fallback на defaults при недоступности backend."""
    try:
        return _normalize_auth_methods(client.get_methods())
    except (httpx.ConnectError, httpx.HTTPError) as exc:
        st.warning(
            f"Не удалось получить список auth-методов: {exc}. "
            "Используются defaults (только password)."
        )
        return _default_auth_methods()


def render_login() -> None:
    """Render login form. После успеха — st.rerun() → auth_state.is_authenticated."""
    if auth_state.is_authenticated():
        # Уже залогинен — редирект на Home
        st.switch_page("../app.py")
        return

    # Logo / title
    col1, col2 = st.columns([1, 3])
    with col1:
        st.markdown("## 🔐")
    with col2:
        st.title("Вход в GD Integration Tools")
        st.caption("Корпоративная интеграционная шина — панель управления")

    st.divider()

    client = AuthClient()
    methods_info = _fetch_methods(client)
    available_methods = methods_info["methods"]
    deprecations = methods_info["deprecations"]

    # UI: tabs если несколько methods, иначе одна форма
    if len(available_methods) > 1:
        tab_labels = [_LOGIN_METHOD_LABELS[method] for method in available_methods]
        tabs = st.tabs(tab_labels)
        for tab, method in zip(tabs, available_methods, strict=True):
            with tab:
                _render_login_form(
                    client, method=method, deprecation_note=deprecations.get(method)
                )
    else:
        method = available_methods[0]
        _render_login_form(
            client, method=method, deprecation_note=deprecations.get(method)
        )

    st.divider()

    # Help block
    with st.expander("Как авторизоваться?", expanded=False):
        st.markdown(
            """
**Вариант 1: Логин / пароль**
- Введите доменный логин (например `ivanov_ii`).
- Пароль — доменный пароль.

**Вариант 2: LDAP / AD**
- Если в компании настроена Active Directory — выберите вкладку LDAP.
- Используется тот же логин/пароль, что и для входа в Windows.

**Где взять ключ доступа (API key)?**
- Для интеграций и внешних вызовов API — выпустите API key
  на странице **Admin → Token Registry** (требуются права администратора).
- API key передаётся в заголовке ``Authorization: Bearer <token>``.
            """
        )


def _render_login_form(
    client: AuthClient,
    *,
    method: Literal["password", "ldap"],
    deprecation_note: str | None,
) -> None:
    """Render a single login form for the given method."""
    if deprecation_note:
        st.warning(f"⚠️ {deprecation_note}")

    with st.form(f"login_form_{method}", clear_on_submit=False):
        username = st.text_input(
            "Логин",
            placeholder="ivanov_ii",
            autocomplete="username",
            key=f"login_username_{method}",
        )
        password = st.text_input(
            "Пароль",
            type="password",
            placeholder="••••••••",
            autocomplete="current-password",
            key=f"login_password_{method}",
        )

        col_btn, col_extra = st.columns([1, 3])
        with col_btn:
            submit = st.form_submit_button(
                _LOGIN_METHOD_LABELS.get(method, method),
                type="primary",
                width="stretch",
            )
        with col_extra:
            if method == "password":
                st.caption("Пароль чувствителен к регистру.")

        if submit:
            if not username or not password:
                st.error("Введите логин и пароль.")
                # S174 M9.4: failed-submission telemetry (security
                # observability — repeated empty-submits могут указывать
                # на credential-stuffing).
                _emit_login_submit_event(outcome="empty", method=method)
                return
            try:
                auth_state.login(username=username, password=password, method=method)
                st.success("Вход выполнен!")
                _emit_login_submit_event(outcome="success", method=method)
                st.rerun()
            except PermissionError as exc:
                st.error(
                    "Неверный логин или пароль. Проверьте данные и попробуйте снова."
                )
                st.caption(f"Backend: {exc}")
                # S174 M9.4: auth-failure telemetry (security).
                _emit_login_submit_event(outcome="auth_failure", method=method)
            except httpx.HTTPError as exc:
                st.error(f"Ошибка соединения с сервером: {exc}")
                _emit_login_submit_event(outcome="connection_error", method=method)


# S174 M9.4: login-submit audit-event helper.
def _emit_login_submit_event(*, outcome: str, method: str) -> None:
    """Emit ``frontend.auth.login_submit`` audit-event.

    Args:
        outcome: ``success`` / ``auth_failure`` / ``empty`` /
            ``connection_error``.
        method: ``password`` / ``ldap``.

    Notes:
        Lightweight — non-blocking. Lazy-import emit_audit_safe
        (dev-envs без DI не сломаются). Graceful fallback.

        Signature: ``emit_audit_safe(*, event, action='', outcome,
        details=None, severity=None, extra=None)``.
    """
    try:
        from src.backend.core.frontend_facade import emit_audit_safe

        emit_audit_safe(
            event="frontend.auth.login_submit",
            action="auth.login_submit",
            outcome=("success" if outcome == "success" else "failure"),
            details={
                "submit_outcome": outcome,
                "method": method,
                "page_key": "00_Вход",
            },
            severity=("info" if outcome == "success" else "warning"),
        )
    except Exception as _exc:  # pragma: no cover — never fail caller
        import logging as _logging

        _logging.getLogger("frontend.pages.00_Вход").debug(
            "frontend.auth.login_submit: audit-event emit failed: %s", _exc
        )


# Streamlit entry point
render_login()
