"""Sessions — список активных LangGraph-сессий с чекпоинтами.

Заменяет admin-react SessionList.tsx. Данные берутся из
``GET /api/v1/admin/langgraph/checkpoints``.

S27 Wave 3: SessionList migration → Streamlit.
"""

from __future__ import annotations

import streamlit as st

from src.frontend.streamlit_app.api_clients.admin import AdminClient

st.set_page_config(page_title="Sessions", page_icon=":bank:", layout="wide")
st.header(":bank: LangGraph Sessions")

client = AdminClient()

col1, col2, col3 = st.columns(3)
limit = col1.number_input("Лимит", min_value=1, max_value=500, value=50)
offset = col2.number_input("Смещение", min_value=0, value=0)
refresh = col3.button("Обновить")

if refresh or "sessions_data" not in st.session_state:
    data = client.get_langgraph_sessions(limit=limit, offset=offset)
    st.session_state.sessions_data = data
else:
    data = st.session_state.sessions_data

sessions = data.get("sessions", [])
count = data.get("count", 0)
error = data.get("error")

if error:
    st.warning(f"Не удалось получить сессии: {error}")

st.caption(f"Активных сессий: {count}")

if not sessions:
    st.info("Нет активных сессий.")
else:
    # Маппинг полей из LangGraph SessionInfo в формат для отображения
    display_rows = []
    for s in sessions:
        display_rows.append(
            {
                "Session ID": s.get("session_id", ""),
                "Last Checkpoint": s.get("last_checkpoint_id", ""),
                "Updated At": s.get("updated_at", ""),
                "Checkpoint Count": s.get("checkpoint_count", 0),
            }
        )

    st.dataframe(display_rows, use_container_width=True, height=500)

    # Детали по выбранной сессии
    if display_rows:
        st.divider()
        selected_id = st.selectbox(
            "Выберите сессию для детализации",
            options=[s["Session ID"] for s in display_rows],
        )
        if selected_id:
            st.json(
                data={
                    "session_id": selected_id,
                    "note": "Детали доступны через GET /api/v1/admin/langgraph/checkpoints/{session_id}",
                }
            )
