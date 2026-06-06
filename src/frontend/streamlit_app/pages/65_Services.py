"""External Services — ссылки на внешние сервисы с живым статусом."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

import httpx
import streamlit as st

from src.frontend.streamlit_app.shared.components import setup_page

from src.frontend.streamlit_app.api_clients import get_api_client

setup_page('Services', ':link:')
st.header("External Services")

client = get_api_client()


class ServiceStatus(Enum):
    UP = "up"
    DOWN = "down"
    UNKNOWN = "unknown"


@dataclass
class ServiceInfo:
    name: str
    url: str | None
    status: ServiceStatus = ServiceStatus.UNKNOWN
    latency_ms: int | None = None
    description: str = ""


def _ping_url(url: str, timeout: float = 3.0) -> tuple[ServiceStatus, int | None]:
    """Ping URL, return (status, latency_ms)."""
    if not url:
        return ServiceStatus.UNKNOWN, None
    try:
        start = __import__("time").time()
        response = httpx.get(url, timeout=timeout, follow_redirects=True)
        latency = int((__import__("time").time() - start) * 1000)
        if response.status_code < 500:
            return ServiceStatus.UP, latency
        return ServiceStatus.DOWN, latency
    except Exception:
        return ServiceStatus.DOWN, None


def _build_services() -> list[ServiceInfo]:
    """Build service list from config + live health checks."""
    try:
        config = client.get_config()
    except Exception:
        config = {}
    try:
        client.get_health()  # verify endpoint reachable
    except Exception:  # noqa: S110
        pass

    services_raw: list[dict[str, Any]] = [
        {
            "name": "S3 / MinIO",
            "url": config.get("storage_interface_endpoint"),
            "description": "Object storage",
        },
        {
            "name": "Graylog",
            "url": config.get("graylog_url"),
            "description": "Log aggregation",
        },
        {
            "name": "LangFuse",
            "url": config.get("langfuse_url"),
            "description": "AI observability",
        },
        {
            "name": "RabbitMQ",
            "url": config.get("queue_ui_url"),
            "description": "Message queue UI",
        },
    ]

    result: list[ServiceInfo] = []
    for svc in services_raw:
        url = svc["url"]
        status, latency = _ping_url(url) if url else (ServiceStatus.UNKNOWN, None)
        result.append(
            ServiceInfo(
                name=svc["name"],
                url=url,
                status=status,
                latency_ms=latency,
                description=svc["description"],
            )
        )
    return result


st.subheader("Infrastructure Services")
services = _build_services()

cols = st.columns(len(services) if services else 1)
for i, svc in enumerate(services):
    with cols[i]:
        if svc.url:
            st.link_button(svc.name, svc.url, use_container_width=True)
        else:
            st.button(svc.name, disabled=True, use_container_width=True)

        if svc.status == ServiceStatus.UP:
            st.markdown(
                f":green[{svc.status.value.upper()}]"
                + (f" ({svc.latency_ms}ms)" if svc.latency_ms else "")
            )
        elif svc.status == ServiceStatus.DOWN:
            st.markdown(":red[DOWN]" + (" — check connectivity" if svc.url else ""))
        else:
            st.markdown(":gray[URL not configured]")

        if svc.description:
            st.caption(svc.description)


st.divider()
st.subheader("Documentation portals")
try:
    config = client.get_config()
except Exception:
    config = {}
base_url = config.get("base_url", "http://localhost:8000")

doc_services: dict[str, str] = {
    "Swagger UI": "/docs",
    "ReDoc": "/redoc",
    "AsyncAPI": "/asyncapi",
    "OpenAPI JSON": "/openapi.json",
}
doc_cols = st.columns(len(doc_services))
for i, (name, path) in enumerate(doc_services.items()):
    with doc_cols[i]:
        st.link_button(name, f"{base_url}{path}", use_container_width=True)
