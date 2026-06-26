"""Шина действий — страница вызова зарегистрированных actions (K5 W2).

Позволяет:

* просматривать список зарегистрированных actions (name/description/namespace/tier);
* выбирать action из selectbox;
* редактировать JSON-payload в text_area;
* выбирать режим вызова: sync / async-fire-and-forget / async-api;
* вызывать action через кнопку Invoke и видеть результат в st.code;
* раскрывать metadata (description + params JSON-Schema) через st.expander.

Страница активна только при ``feature_flags.frontend_action_bus_ui = True``.
При выключенном флаге показывает предупреждение и останавливает рендер.
"""

from __future__ import annotations

import json

# Добавляем корень проекта в sys.path для корректного импорта в Streamlit-режиме
import streamlit as st

from src.frontend.streamlit_app.shared.components import (
    related_pages_footer,
    setup_page,
)

setup_page()
st.header("Шина действий")

# ---------------------------------------------------------------------------
# Feature-flag guard
# ---------------------------------------------------------------------------
try:
    from src.backend.core.config.features import feature_flags as _ff  # noqa: PLC0415

    _flag_enabled: bool = _ff.frontend_action_bus_ui
except Exception:  # noqa: BLE001
    _flag_enabled = False

with st.sidebar:
    st.subheader("Настройки")
    _sidebar_toggle = st.toggle(
        "UI шины действий",
        value=_flag_enabled,
        help="feature_flags.frontend_action_bus_ui (FEATURE_FRONTEND_ACTION_BUS_UI)",
        disabled=True,  # изменение только через env/config
    )
    st.caption(
        "Для включения установите `FEATURE_FRONTEND_ACTION_BUS_UI=true` "
        "или измените `features.yaml`."
    )

if not _flag_enabled:
    st.warning(
        "UI шины действий отключён (feature_flag: `frontend_action_bus_ui = false`). "
        "Установите `FEATURE_FRONTEND_ACTION_BUS_UI=true` для активации."
    )
    st.stop()

# ---------------------------------------------------------------------------
# Клиент
# ---------------------------------------------------------------------------
from src.frontend.streamlit_app.services.action_bus_client import (  # noqa: PLC0415, E402
    get_action_spec,
    invoke,
    list_actions,
)

# ---------------------------------------------------------------------------
# Загрузка списка actions (кэш на 30 секунд)
# ---------------------------------------------------------------------------


@st.cache_data(ttl=30)
def _cached_list_actions() -> list[dict]:
    """Загружает список actions с кэшем TTL=30s.

    Returns:
        Список словарей action-метаданных.
    """
    return list_actions()


_actions: list[dict] = _cached_list_actions()

if not _actions:
    st.info("Нет зарегистрированных actions или backend недоступен.")
    st.stop()

# ---------------------------------------------------------------------------
# Основной layout: left — список, right — invoke-форма
# ---------------------------------------------------------------------------
col_list, col_invoke = st.columns([1, 2], gap="large")

with col_list:
    st.subheader("Зарегистрированные actions")
    for _act in _actions:
        _tier = _act.get("tier", "?")
        _ns = _act.get("namespace", "")
        _desc = _act.get("description", "")
        with st.expander(f"**{_act.get('name', '')}**  `tier:{_tier}`"):
            if _desc:
                st.write(_desc)
            if _ns:
                st.caption(f"namespace: `{_ns}`")

with col_invoke:
    st.subheader("Вызов action")

    _action_names: list[str] = [a.get("name", "") for a in _actions if a.get("name")]
    _selected_action: str = st.selectbox(
        "Action",
        options=_action_names,
        help="Выберите action из списка зарегистрированных",
    )

    _payload_raw: str = st.text_area(
        "JSON-payload", value="{}", height=150, help="Тело запроса в формате JSON"
    )

    _mode: str = st.selectbox(
        "Режим вызова",
        options=["sync", "async-fire-and-forget", "async-api"],
        help=(
            "sync — ждёт результат; "
            "async-fire-and-forget — не ждёт; "
            "async-api — возвращает invocation_id для polling"
        ),
    )

    _invoke_clicked = st.button("Вызвать", type="primary", width='stretch')

    if _invoke_clicked:
        # Валидация JSON
        try:
            _payload: dict = json.loads(_payload_raw)
        except json.JSONDecodeError as _json_err:
            st.error(f"Невалидный JSON-payload: {_json_err}")
        else:
            with st.spinner(f"Вызов `{_selected_action}` в режиме `{_mode}`..."):
                _result = invoke(_selected_action, _payload, _mode)
            st.success("Ответ получен")
            st.code(json.dumps(_result, ensure_ascii=False, indent=2), language="json")

    # Metadata expander
    with st.expander("Метаданные регистрации"):
        if _selected_action:
            _spec = get_action_spec(_selected_action)
            if _spec:
                st.write(f"**Описание**: {_spec.get('description', '—')}")
                _params_schema = _spec.get("params_schema")
                if _params_schema:
                    st.write("**JSON-схема параметров**:")
                    st.code(
                        json.dumps(_params_schema, ensure_ascii=False, indent=2),
                        language="json",
                    )
                _result_schema = _spec.get("result_schema")
                if _result_schema:
                    st.write("**JSON-схема результата**:")
                    st.code(
                        json.dumps(_result_schema, ensure_ascii=False, indent=2),
                        language="json",
                    )
                # Полная спецификация
                st.write("**Полная спецификация**:")
                st.code(
                    json.dumps(_spec, ensure_ascii=False, indent=2), language="json"
                )
            else:
                st.info(f"Спецификация для `{_selected_action}` не найдена (404).")

related_pages_footer("58_Шина_действий")
