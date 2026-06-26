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
                return
            try:
                auth_state.login(username=username, password=password, method=method)
                st.success("Вход выполнен!")
                st.rerun()
            except PermissionError as exc:
                st.error(
                    "Неверный логин или пароль. Проверьте данные и попробуйте снова."
                )
                st.caption(f"Backend: {exc}")
            except httpx.HTTPError as exc:
                st.error(f"Ошибка соединения с сервером: {exc}")


# Streamlit entry point
render_login()
