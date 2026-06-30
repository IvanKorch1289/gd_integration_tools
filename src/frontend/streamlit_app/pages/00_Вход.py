"""Login page — S169.

Auth gate: пользователь видит эту страницу до успешного login.
После login — редирект на ``00_Главная``.

Backend endpoints:
* ``GET /auth/methods`` — список available methods.
* ``POST /auth/login`` — аутентификация.

Streamlit auto-discovers ``00_*.py`` файлы в ``pages/`` и сортирует
по имени. Префикс ``00_`` ставим выше Home (тоже ``00_``), добавляем
``_Login`` суффикс чтобы сортировка шла первой.
"""

from __future__ import annotations

from typing import Literal

import httpx
import streamlit as st

from src.frontend.streamlit_app.api_clients.auth import AuthClient
from src.frontend.streamlit_app.shared import auth_state

_LOGIN_METHOD_LABELS: dict[str, str] = {
    "password": "Логин / пароль",
    "ldap": "LDAP / AD",
}


def _fetch_methods(client: AuthClient) -> dict[str, object]:
    """``GET /auth/methods`` с fallback на defaults при недоступности backend."""
    try:
        return client.get_methods()  # type: ignore[no-any-return]
    except (httpx.ConnectError, httpx.HTTPError) as exc:
        st.warning(
            f"Не удалось получить список auth-методов: {exc}. "
            "Используются defaults (только password)."
        )
        return {
            "methods": ["password"],
            "ldap_enabled": False,
            "password_enabled": True,
            "default_method": "password",
            "deprecations": {},
        }


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
    available_methods: list[str] = methods_info.get("methods", ["password"])  # type: ignore[assignment]
    methods_info.get("default_method", "password")  # type: ignore[assignment]

    # UI: tabs если несколько methods, иначе одна форма
    if len(available_methods) > 1:
        tab_labels = [_LOGIN_METHOD_LABELS.get(m, m) for m in available_methods]
        tabs = st.tabs(tab_labels)
        for tab, method in zip(tabs, available_methods, strict=True):
            with tab:
                _render_login_form(
                    client,
                    method=method,  # type: ignore[arg-type]
                    deprecation_note=methods_info.get("deprecations", {}).get(method),  # type: ignore[union-attr]
                )
    else:
        method = available_methods[0] if available_methods else "password"
        _render_login_form(
            client,
            method=method,  # type: ignore[arg-type]
            deprecation_note=methods_info.get("deprecations", {}).get(method),  # type: ignore[union-attr]
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
                width='stretch',
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
                _emit_login_submit_event(
                    outcome="empty",
                    method=method,
                )
                return
            try:
                auth_state.login(username=username, password=password, method=method)
                st.success("Вход выполнен!")
                _emit_login_submit_event(
                    outcome="success",
                    method=method,
                )
                st.rerun()
            except PermissionError as exc:
                st.error(
                    "Неверный логин или пароль. Проверьте данные и попробуйте снова."
                )
                st.caption(f"Backend: {exc}")
                # S174 M9.4: auth-failure telemetry (security).
                _emit_login_submit_event(
                    outcome="auth_failure",
                    method=method,
                )
            except httpx.HTTPError as exc:
                st.error(f"Ошибка соединения с сервером: {exc}")
                _emit_login_submit_event(
                    outcome="connection_error",
                    method=method,
                )


# S174 M9.4: login-submit audit-event helper.
def _emit_login_submit_event(
    *,
    outcome: str,
    method: str,
) -> None:
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
        from src.backend.core.audit.facade import emit_audit_safe

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
