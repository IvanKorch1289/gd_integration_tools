"""REST API Caller — универсальный клиент к backend из UI.

Позволяет вручную выполнить любой эндпоинт приложения без curl/Postman.
Сохраняет историю последних 20 вызовов в ``st.session_state``.
"""

from __future__ import annotations

import json
import os
import time

import httpx
import streamlit as st

st.set_page_config(
    page_title="API Caller", page_icon=":satellite_antenna:", layout="wide"
)
st.header(":satellite_antenna: REST API Caller")

BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")

col1, col2 = st.columns([1, 3])
method = col1.selectbox("Метод", ["GET", "POST", "PUT", "PATCH", "DELETE"])
path = col2.text_input(
    "Путь", value="/api/v1/health/components", help="Относительный путь от BASE_URL"
)

headers_raw = st.text_area(
    "Headers (JSON)", value='{\n  "Content-Type": "application/json"\n}', height=100
)
body_raw = st.text_area("Body (JSON)", value="", height=150) if method != "GET" else ""

if "api_history" not in st.session_state:
    st.session_state["api_history"] = []

if st.button("Отправить", type="primary"):
    try:
        headers = json.loads(headers_raw) if headers_raw.strip() else {}
    except Exception as exc:  # noqa: BLE001
        st.error(f"Невалидные headers: {exc}")
        headers = None

    body = None
    if method != "GET" and body_raw.strip():
        try:
            body = json.loads(body_raw)
        except Exception as exc:  # noqa: BLE001
            st.error(f"Невалидный body: {exc}")
            body = None

    if headers is not None:
        started = time.perf_counter()
        try:
            with httpx.Client(timeout=30) as client:
                kwargs = {"headers": headers}
                if body is not None:
                    kwargs["json"] = body
                resp = client.request(method, f"{BASE_URL}{path}", **kwargs)
            elapsed_ms = (time.perf_counter() - started) * 1000
            st.metric("Статус", resp.status_code)
            st.metric("Время, мс", f"{elapsed_ms:.1f}")
            try:
                st.json(resp.json())
            except Exception:  # noqa: BLE001
                st.code(resp.text[:10_000])

            st.session_state["api_history"].insert(
                0,
                {
                    "method": method,
                    "path": path,
                    "status": resp.status_code,
                    "ms": round(elapsed_ms),
                },
            )
            st.session_state["api_history"] = st.session_state["api_history"][:20]
        except Exception as exc:  # noqa: BLE001
            st.error(str(exc))

st.divider()
st.subheader("История")
for item in st.session_state.get("api_history", []):
    st.write(
        f"{item['method']} `{item['path']}` — **{item['status']}** ({item['ms']} ms)"
    )
