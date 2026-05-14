"""Plugin Marketplace — управление установленными плагинами (K5 W3).

Позволяет:

* просматривать список установленных плагинов с фильтрацией по статусу;
* включать / отключать плагины через action-кнопки;
* раскрывать manifest (plugin.toml) и метрики каждого плагина;
* видеть capabilities, routes_count, actions_count в компактной таблице.

Страница активна только при ``feature_flags.frontend_plugin_marketplace = True``.
При выключенном флаге показывает предупреждение и останавливает рендер.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Добавляем корень проекта в sys.path для корректного импорта в Streamlit-режиме
_project_root = Path(__file__).resolve().parents[4]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import streamlit as st

st.set_page_config(
    page_title="Plugin Marketplace",
    page_icon=":electric_plug:",
    layout="wide",
)
st.title("Plugin Marketplace")

# ---------------------------------------------------------------------------
# Feature-flag guard
# ---------------------------------------------------------------------------
try:
    from src.backend.core.config.features import feature_flags as _ff  # noqa: PLC0415

    _flag_enabled: bool = _ff.frontend_plugin_marketplace
except Exception:  # noqa: BLE001
    _flag_enabled = False

with st.sidebar:
    st.subheader("Настройки")
    st.toggle(
        "Plugin Marketplace UI",
        value=_flag_enabled,
        help="feature_flags.frontend_plugin_marketplace (FEATURE_FRONTEND_PLUGIN_MARKETPLACE)",
        disabled=True,
    )
    st.caption(
        "Для включения установите `FEATURE_FRONTEND_PLUGIN_MARKETPLACE=true` "
        "или измените `features.yaml`."
    )
    st.divider()

    # ── Фильтр по статусу ──────────────────────────────────────────────────
    _status_filter: str = st.radio(
        "Filter by status",
        options=["all", "active", "disabled"],
        index=0,
        help="Отображать только плагины с выбранным статусом.",
    )

if not _flag_enabled:
    st.warning(
        "Plugin Marketplace отключён "
        "(feature_flag: `frontend_plugin_marketplace = false`). "
        "Установите `FEATURE_FRONTEND_PLUGIN_MARKETPLACE=true` для активации."
    )
    st.stop()

# ---------------------------------------------------------------------------
# Клиент (импортируем после guard, чтобы не тянуть httpx без нужды)
# ---------------------------------------------------------------------------
from src.frontend.streamlit_app.services.plugin_marketplace_client import (  # noqa: PLC0415, E402
    get_plugin_manifest,
    list_plugins,
    toggle_plugin,
)

# ---------------------------------------------------------------------------
# Загрузка данных (кэш на 30 секунд)
# ---------------------------------------------------------------------------


@st.cache_data(ttl=30)  # type: ignore[misc]
def _cached_list_plugins(status: str) -> list[dict]:
    """Загружает список плагинов с кэшем TTL=30s.

    Args:
        status: Фильтр статуса — ``"all"``, ``"active"`` или ``"disabled"``.

    Returns:
        Список словарей метаданных плагинов.
    """
    return list_plugins(status_filter=status)


_plugins: list[dict] = _cached_list_plugins(_status_filter)

# ---------------------------------------------------------------------------
# Installed plugins — таблица
# ---------------------------------------------------------------------------
st.subheader("Installed plugins")

if not _plugins:
    st.info("Нет плагинов, соответствующих выбранному фильтру.")
    st.stop()

# Строим сводные строки для st.dataframe
_table_rows = []
for _p in _plugins:
    _caps = _p.get("capabilities") or []
    _caps_str = ", ".join(_caps[:3]) + (f"… (+{len(_caps) - 3})" if len(_caps) > 3 else "")
    _table_rows.append(
        {
            "Имя": _p.get("name", "—"),
            "Версия": _p.get("version", "—"),
            "Статус": _p.get("status", "—"),
            "Capabilities": _caps_str or "—",
            "Routes": _p.get("routes_count", 0),
            "Actions": _p.get("actions_count", 0),
        }
    )

st.dataframe(_table_rows, use_container_width=True, hide_index=True)

# ---------------------------------------------------------------------------
# Детальные expander'ы с manifest и action-кнопками
# ---------------------------------------------------------------------------
for _plugin in _plugins:
    _name: str = _plugin.get("name", "unknown")
    _status: str = _plugin.get("status", "unknown")
    _version: str = _plugin.get("version", "—")
    _is_active: bool = _status == "active"

    with st.expander(f"**{_name}** `v{_version}`  —  `{_status}`", expanded=False):
        col_info, col_actions = st.columns([3, 1])

        with col_info:
            st.markdown(f"**Описание:** {_plugin.get('description', '—')}")
            st.markdown(f"**tenant_aware:** `{_plugin.get('tenant_aware', False)}`")
            _caps_list = _plugin.get("capabilities") or []
            if _caps_list:
                st.markdown("**Capabilities:**")
                for _cap in _caps_list:
                    st.markdown(f"- `{_cap}`")
            else:
                st.markdown("**Capabilities:** —")

            # Manifest (plugin.toml)
            _manifest: dict | None = get_plugin_manifest(_name)
            if _manifest:
                st.markdown("**Manifest (plugin.toml):**")
                import json  # noqa: PLC0415

                st.code(
                    json.dumps(_manifest, ensure_ascii=False, indent=2),
                    language="json",
                )
            else:
                st.caption("Manifest недоступен.")

        with col_actions:
            st.markdown(f"Routes: **{_plugin.get('routes_count', 0)}**")
            st.markdown(f"Actions: **{_plugin.get('actions_count', 0)}**")
            st.divider()

            _btn_label = "Disable" if _is_active else "Enable"
            _btn_type = "secondary" if _is_active else "primary"

            if st.button(
                _btn_label,
                key=f"toggle_{_name}",
                type=_btn_type,
                use_container_width=True,
                help=f"{'Отключить' if _is_active else 'Включить'} плагин {_name}",
            ):
                _ok = toggle_plugin(_name, not _is_active)
                if _ok:
                    _new_status = "disabled" if _is_active else "active"
                    st.toast(f"Плагин `{_name}` → **{_new_status}**")
                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.error(f"Не удалось изменить статус плагина `{_name}`.")
