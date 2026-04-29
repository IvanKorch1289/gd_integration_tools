"""External Services — ссылки на внешние сервисы."""

import sys
from pathlib import Path

import streamlit as st

_root = Path(__file__).resolve().parents[4]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from src.entrypoints.streamlit_app.api_client import get_api_client

st.set_page_config(page_title="Services", page_icon=":link:", layout="wide")
st.header("External Services")

client = get_api_client()

try:
    config = client.get_config()
except Exception:
    config = {}

services = {
    "S3 / MinIO": config.get("storage_interface_endpoint"),
    "Graylog": config.get("graylog_url"),
    "LangFuse": config.get("langfuse_url"),
    "RabbitMQ": config.get("queue_ui_url"),
}

doc_services = {"Swagger UI": "/docs", "ReDoc": "/redoc", "AsyncAPI": "/asyncapi"}

st.subheader("Infrastructure")
for name, url in services.items():
    if url:
        st.link_button(f"{name}", url, use_container_width=True)
    else:
        st.warning(f"{name} — URL не сконфигурирован")

st.subheader("Documentation")
base_url = config.get("base_url", "http://localhost:8000")
for name, path in doc_services.items():
    st.link_button(f"{name}", f"{base_url}{path}", use_container_width=True)
