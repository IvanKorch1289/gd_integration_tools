"""Realtime Logs — live tail логов через SSE.

Показывает поток структурированных логов с фильтрами по уровню и модулю.
Используется backend-эндпоинт ``/sse/logs`` (Server-Sent Events) — запросов
меньше, чем при polling, и соединение держится открытым.
"""

from __future__ import annotations

import os
import queue
import threading
from typing import Any

import httpx
import streamlit as st

st.set_page_config(page_title="Realtime Logs", page_icon=":memo:", layout="wide")
st.header(":memo: Realtime Logs (live tail)")

BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")

# ── Фильтры
col_a, col_b, col_c = st.columns([2, 2, 1])
level = col_a.selectbox("Минимальный уровень", ["DEBUG", "INFO", "WARNING", "ERROR"], index=1)
module = col_b.text_input("Фильтр по модулю (substring)")
pause = col_c.toggle("Пауза")


@st.cache_resource
def _log_queue() -> queue.Queue:
    """Общая очередь логов — shared state между SSE-потоком и UI."""
    return queue.Queue(maxsize=500)


def _start_sse_thread() -> None:
    """Запускает SSE-подписку в фоне, если ещё не запущена."""
    if st.session_state.get("_sse_started"):
        return
    q = _log_queue()

    def consume() -> None:
        """Фоновый поток: читает /sse/logs и кладёт строки в очередь."""
        try:
            with httpx.stream("GET", f"{BASE_URL}/sse/logs", timeout=None) as resp:
                for line in resp.iter_lines():
                    if line.startswith("data:"):
                        payload = line[5:].strip()
                        if payload:
                            try:
                                q.put_nowait(payload)
                            except queue.Full:
                                q.get_nowait()  # вытесняем старое
                                q.put_nowait(payload)
        except Exception:  # noqa: BLE001
            pass  # backend недоступен; UI покажет это в хедере

    threading.Thread(target=consume, daemon=True, name="sse-logs").start()
    st.session_state["_sse_started"] = True


_start_sse_thread()

# ── Забор пачки логов
q = _log_queue()
batch: list[dict[str, Any]] = []
while not q.empty() and len(batch) < 100:
    try:
        import orjson
        batch.append(orjson.loads(q.get_nowait()))
    except Exception:  # noqa: BLE001
        continue

if "log_history" not in st.session_state:
    st.session_state["log_history"] = []

if not pause:
    st.session_state["log_history"] = (st.session_state["log_history"] + batch)[-1000:]

levels_order = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40}
threshold = levels_order[level]
filtered = [
    item
    for item in st.session_state["log_history"]
    if levels_order.get(str(item.get("level", "INFO")).upper(), 20) >= threshold
    and (not module or module.lower() in str(item.get("logger", "")).lower())
]

# ── Отображение
st.caption(f"Записей в буфере: {len(st.session_state['log_history'])}, после фильтра: {len(filtered)}")
for item in reversed(filtered[-200:]):
    ts = item.get("timestamp", "")
    lvl = item.get("level", "INFO")
    msg = item.get("event") or item.get("message", "")
    logger_name = item.get("logger", "—")
    icon = ":red_circle:" if lvl == "ERROR" else ":large_orange_circle:" if lvl == "WARNING" else ":large_blue_circle:"
    st.markdown(f"{icon} `{ts}` **{logger_name}** — {msg}")

# Авто-рефреш каждые 2с
if not pause:
    import time
    time.sleep(2)
    st.rerun()
