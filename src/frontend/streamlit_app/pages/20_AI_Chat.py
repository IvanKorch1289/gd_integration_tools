"""AI Assistant — чат с AI-агентом."""

import sys
from pathlib import Path

import streamlit as st

_root = Path(__file__).resolve().parents[4]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from src.frontend.streamlit_app.api_client import get_api_client

st.set_page_config(page_title="AI Chat", page_icon=":robot_face:", layout="wide")
st.header("AI Assistant")

client = get_api_client()

# ──────────── Session state ────────────

if "messages" not in st.session_state:
    st.session_state.messages = []

if "session_id" not in st.session_state:
    import uuid

    st.session_state.session_id = str(uuid.uuid4())[:8]

# ──────────── Chat history ────────────

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])

# ──────────── Input ────────────

if prompt := st.chat_input("Задайте вопрос..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.write(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Думаю..."):
            try:
                response = client.chat(prompt, st.session_state.session_id)
            except Exception as exc:
                response = f"Ошибка: {exc}"
        st.write(response)

    st.session_state.messages.append({"role": "assistant", "content": response})

# ──────────── Controls ────────────

col1, col2 = st.columns([1, 5])
with col1:
    if st.button("Очистить"):
        st.session_state.messages = []
        import uuid

        st.session_state.session_id = str(uuid.uuid4())[:8]
        st.rerun()
with col2:
    st.caption(f"Session: {st.session_state.session_id}")
