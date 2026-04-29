"""Invocation Console — UI для :class:`Invoker` (W22.5).

Минималистичная консоль, чтобы вручную запускать action в любом из
шести режимов :class:`InvocationMode` и видеть результаты:

* ``sync`` / ``error`` — результат сразу из POST /api/v1/invocations.
* ``async-api`` / ``background`` / ``deferred`` / ``async-queue`` —
  GET /api/v1/invocations/{id} (polling).
* ``streaming`` — instructive только: для real-time chunks нужен
  отдельный WS-клиент (``/ws/invocations``).

Хранит историю последних 20 вызовов в ``st.session_state``.
"""

from __future__ import annotations

import json
import os
import time

import httpx
import streamlit as st

__all__: tuple[str, ...] = ()

st.set_page_config(
    page_title="Invocation Console",
    page_icon=":zap:",
    layout="wide",
)
st.header(":zap: Invocation Console (W22)")

BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")

MODES = ("sync", "async-api", "async-queue", "deferred", "background", "streaming")
REPLY_KINDS = ("", "api", "ws", "queue", "email", "express")

if "invocation_history" not in st.session_state:
    st.session_state["invocation_history"] = []

# ── Форма запуска ────────────────────────────────────────────────────────

with st.form("invoke-form"):
    col1, col2 = st.columns([3, 2])
    action = col1.text_input(
        "Action",
        value="users.list",
        help="Имя action в ActionDispatcher (e.g. 'orders.add').",
    )
    mode = col2.selectbox("Mode", MODES, index=0)

    payload_raw = st.text_area(
        "Payload (JSON)",
        value="{}",
        height=120,
        help="JSON-объект, который будет передан action.",
    )
    reply_channel = st.selectbox(
        "Reply channel",
        REPLY_KINDS,
        index=0,
        help="Тип канала ответа. Пусто = выбирается автоматически по mode.",
    )

    submitted = st.form_submit_button("Invoke", type="primary")

if submitted:
    try:
        payload = json.loads(payload_raw or "{}")
        if not isinstance(payload, dict):
            raise ValueError("payload must be a JSON object")
    except Exception as exc:  # noqa: BLE001
        st.error(f"Невалидный payload: {exc}")
        st.stop()

    body: dict[str, object] = {"action": action, "mode": mode, "payload": payload}
    if reply_channel:
        body["reply_channel"] = reply_channel

    started = time.perf_counter()
    try:
        with httpx.Client(timeout=30) as client:
            resp = client.post(f"{BASE_URL}/api/v1/invocations", json=body)
        elapsed_ms = (time.perf_counter() - started) * 1000
    except Exception as exc:  # noqa: BLE001
        st.error(f"HTTP error: {exc}")
        st.stop()

    cols = st.columns(3)
    cols[0].metric("HTTP", resp.status_code)
    cols[1].metric("Время, мс", f"{elapsed_ms:.1f}")
    try:
        data = resp.json()
        cols[2].metric("Status", data.get("status", "—"))
        st.json(data)
        invocation_id = data.get("invocation_id")
        if invocation_id and data.get("status") == "accepted":
            st.info(
                f"Используйте polling: `GET /api/v1/invocations/{invocation_id}` "
                f"(см. кнопку «Опросить» ниже)."
            )
        st.session_state["invocation_history"].insert(
            0,
            {
                "action": action,
                "mode": mode,
                "status": data.get("status", "—"),
                "invocation_id": data.get("invocation_id", "—"),
                "ms": round(elapsed_ms),
            },
        )
        st.session_state["invocation_history"] = st.session_state[
            "invocation_history"
        ][:20]
    except Exception:  # noqa: BLE001
        st.code(resp.text[:10_000])

# ── Polling-форма ────────────────────────────────────────────────────────

st.divider()
st.subheader("Polling результата (для async/streaming через 'api' channel)")

poll_id = st.text_input("invocation_id", value="", key="poll-id")
if st.button("Опросить") and poll_id:
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.get(f"{BASE_URL}/api/v1/invocations/{poll_id}")
        if resp.status_code == 404:
            st.warning(
                "Результат ещё не готов или invocation_id неизвестен. "
                "Повторите попытку."
            )
        else:
            st.metric("HTTP", resp.status_code)
            try:
                st.json(resp.json())
            except Exception:  # noqa: BLE001
                st.code(resp.text[:10_000])
    except Exception as exc:  # noqa: BLE001
        st.error(f"HTTP error: {exc}")

# ── История ──────────────────────────────────────────────────────────────

st.divider()
st.subheader("История последних 20 вызовов")
for item in st.session_state.get("invocation_history", []):
    st.write(
        f"`{item['mode']}` **{item['action']}** "
        f"— status=`{item['status']}` id=`{item['invocation_id']}` "
        f"({item['ms']} ms)"
    )

# ── Подсказка ────────────────────────────────────────────────────────────

st.divider()
st.caption(
    "Streaming через WebSocket: `ws://localhost:8000/ws/invocations`. "
    "Сообщение клиента: `{\"type\": \"invoke\", \"action\": \"...\", \"mode\": "
    "\"streaming\", \"payload\": {...}}`. "
    "Сервер пушит chunks по `invocation_id` и закрытие соединения."
)
