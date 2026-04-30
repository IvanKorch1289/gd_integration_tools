"""Invocation Console — UI для :class:`Invoker` (W22.5).

Минималистичная консоль, чтобы вручную запускать action в любом из
шести режимов :class:`InvocationMode` и видеть результаты:

* ``sync`` / ``error`` — результат сразу из POST /api/v1/invocations.
* ``async-api`` / ``background`` / ``deferred`` / ``async-queue`` —
  GET /api/v1/invocations/{id} (polling).
* ``streaming`` — live chunks через WebSocket (``/ws/invocations``).

Хранит историю последних 20 вызовов в ``st.session_state``.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any

import httpx
import streamlit as st
import websockets

__all__: tuple[str, ...] = ()

st.set_page_config(page_title="Invocation Console", page_icon=":zap:", layout="wide")
st.header(":zap: Invocation Console (W22)")

BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")
WS_URL = os.environ.get(
    "API_WS_URL", BASE_URL.replace("https://", "wss://").replace("http://", "ws://")
)
WS_INVOCATIONS_PATH = "/ws/invocations"
WS_IDLE_TIMEOUT_SECONDS = 5.0


async def _stream_invocation(
    *, action: str, payload: dict[str, Any], reply_channel: str | None
) -> tuple[list[dict[str, Any]], str | None]:
    """Открывает WS, шлёт invoke и собирает все приходящие чанки.

    Возвращает кортеж ``(chunks, error)``: список JSON-сообщений сервера
    и опциональный текст ошибки. Завершает чтение по тайм-ауту простоя
    ``WS_IDLE_TIMEOUT_SECONDS`` либо по нормальному закрытию сокета.
    """
    msg: dict[str, Any] = {
        "type": "invoke",
        "action": action,
        "mode": "streaming",
        "payload": payload,
    }
    if reply_channel:
        msg["reply_channel"] = reply_channel
    chunks: list[dict[str, Any]] = []
    try:
        async with websockets.connect(
            f"{WS_URL}{WS_INVOCATIONS_PATH}", open_timeout=10
        ) as ws:
            await ws.send(json.dumps(msg))
            while True:
                try:
                    raw = await asyncio.wait_for(
                        ws.recv(), timeout=WS_IDLE_TIMEOUT_SECONDS
                    )
                except asyncio.TimeoutError:
                    return chunks, None
                except websockets.ConnectionClosedOK:
                    return chunks, None
                try:
                    chunks.append(json.loads(raw))
                except json.JSONDecodeError:
                    chunks.append({"raw": raw})
    except Exception as exc:  # noqa: BLE001
        return chunks, f"{type(exc).__name__}: {exc}"


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
    if mode == "streaming":
        # Live chunks через WebSocket — отдельный кодпуть.
        with st.spinner("Стриминг через WS..."):
            chunks, err = asyncio.run(
                _stream_invocation(
                    action=action, payload=payload, reply_channel=reply_channel or None
                )
            )
        elapsed_ms = (time.perf_counter() - started) * 1000

        cols = st.columns(3)
        cols[0].metric("Channel", "WebSocket")
        cols[1].metric("Время, мс", f"{elapsed_ms:.1f}")
        cols[2].metric("Chunks", len(chunks))

        if err:
            st.error(f"WS error: {err}")
        if chunks:
            st.write("**Поток сообщений:**")
            for idx, chunk in enumerate(chunks, 1):
                with st.expander(
                    f"#{idx} · status={chunk.get('status', chunk.get('type', '—'))}"
                ):
                    st.json(chunk)
            ack_chunks = [c for c in chunks if c.get("type") == "ack"]
            invocation_id = ack_chunks[0].get("invocation_id") if ack_chunks else "—"
            last_status = next(
                (c.get("status") for c in reversed(chunks) if c.get("status")),
                "streamed",
            )
        else:
            invocation_id = "—"
            last_status = "no-chunks" if not err else "error"

        st.session_state["invocation_history"].insert(
            0,
            {
                "action": action,
                "mode": mode,
                "status": last_status,
                "invocation_id": invocation_id,
                "ms": round(elapsed_ms),
            },
        )
        st.session_state["invocation_history"] = st.session_state["invocation_history"][
            :20
        ]
    else:
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
    f"Streaming-режим использует WebSocket `{WS_URL}{WS_INVOCATIONS_PATH}` "
    "напрямую из этой страницы (см. блок «Поток сообщений» выше после Invoke). "
    f"Чтение завершается по тайм-ауту простоя {WS_IDLE_TIMEOUT_SECONDS}s или "
    "при штатном закрытии соединения сервером."
)
