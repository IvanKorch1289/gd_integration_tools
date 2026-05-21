"""Admin Console — управление плагинами, пользователями и feature-flags (Sprint 7 Team T4).

Объединяет три admin-функции в одной странице через REST к backend:

* **Plugins** — список установленных плагинов с toggle enable/disable
  (через ``/api/v1/admin/plugins``).
* **Users** — read-only список пользователей (через ``/api/v1/users/all``).
* **Feature Flags** — toggle переключатели (через
  ``/api/v1/admin/feature-flags``).

Страница вызывает только публичный REST-API через
:class:`src.frontend.streamlit_app.api_client.APIClient`. Прямого доступа к
БД/инфраструктуре нет (см. CLAUDE.md § «frontend импортирует только
публичный API»).
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

# Добавляем корень проекта в sys.path для корректного импорта в Streamlit-режиме
_project_root = Path(__file__).resolve().parents[4]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.frontend.streamlit_app.api_client import get_api_client  # noqa: E402

st.set_page_config(page_title="Admin Console", page_icon=":wrench:", layout="wide")
st.header(":wrench: Admin Console")
st.caption(
    "Управление плагинами, пользователями и feature-flags. Все операции "
    "журналируются в audit (Sprint 2)."
)

client = get_api_client()

tab_plugins, tab_users, tab_flags = st.tabs(["Plugins", "Users", "Feature Flags"])

# ---------------------------------------------------------------------------
# Tab: Plugins
# ---------------------------------------------------------------------------
with tab_plugins:
    st.subheader("Установленные плагины")

    try:
        plugins = client._request("GET", "/api/v1/admin/plugins")  # type: ignore[attr-defined]
        if not isinstance(plugins, list):
            plugins = []
    except Exception as exc:  # noqa: BLE001
        plugins = []
        st.warning(f"Не удалось получить список плагинов: {exc}")

    if not plugins:
        st.info("Плагины не найдены или backend недоступен.")
    else:
        st.caption(f"Всего: {len(plugins)}")
        for plugin in plugins:
            name = plugin.get("name", "—")
            version = plugin.get("version", "—")
            status = plugin.get("status", "—")
            is_active = status == "active"
            col_name, col_ver, col_status, col_action = st.columns([3, 1, 1, 1])
            col_name.write(f"**{name}**")
            col_ver.write(f"`{version}`")
            col_status.write(f"`{status}`")
            label = "Disable" if is_active else "Enable"
            if col_action.button(label, key=f"plugin_toggle_{name}"):
                try:
                    client._request(  # type: ignore[attr-defined]
                        "POST",
                        f"/api/v1/admin/plugins/{name}/toggle",
                        json={"active": not is_active},
                    )
                    st.toast(
                        f"Плагин `{name}` → {'disabled' if is_active else 'active'}"
                    )
                    st.rerun()
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Не удалось переключить плагин: {exc}")

# ---------------------------------------------------------------------------
# Tab: Users (read-only)
# ---------------------------------------------------------------------------
with tab_users:
    st.subheader("Пользователи (read-only)")
    st.caption("Полноценное управление пользователями — через `/admin` (sqladmin).")

    try:
        users = client._request("GET", "/api/v1/users/all")  # type: ignore[attr-defined]
        if not isinstance(users, list):
            users = []
    except Exception as exc:  # noqa: BLE001
        users = []
        st.warning(f"Не удалось получить пользователей: {exc}")

    if users:
        st.dataframe(users, use_container_width=True, height=400, hide_index=True)
    else:
        st.info("Пользователи не найдены или endpoint недоступен.")

# ---------------------------------------------------------------------------
# Tab: Feature Flags
# ---------------------------------------------------------------------------
with tab_flags:
    st.subheader("Feature Flags")

    try:
        flags = client.get_flags()
    except Exception as exc:  # noqa: BLE001
        flags = []
        st.warning(f"Не удалось получить флаги: {exc}")

    if not flags:
        st.info("Нет feature-flags или backend недоступен.")
    else:
        st.caption(f"Всего: {len(flags)} флагов")
        for flag in flags:
            name = flag.get("name", "unknown")
            enabled = flag.get("enabled", False)
            description = flag.get("description", "")
            col1, col2 = st.columns([4, 1])
            col1.write(f"**{name}**")
            if description:
                col1.caption(description)
            new_state = col2.toggle(name, value=enabled, key=f"admin_flag_{name}")
            if new_state != enabled:
                success = client.toggle_flag(name, new_state)
                if success:
                    st.toast(f"Flag `{name}` → {'ON' if new_state else 'OFF'}")
                else:
                    st.error(f"Не удалось переключить флаг `{name}`")
