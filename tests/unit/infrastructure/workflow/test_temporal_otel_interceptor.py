"""Contract test: Temporal OTEL-interception (v5 P3-12, inventory §3.1).

Контракт wiring'а: ``TemporalWorkflowBackend.connect`` прокидывает
``TracingInterceptor`` в ``Client.connect`` (trace-context уходит в
workflow/activity headers). End-to-end parent/child требует живого
Temporal server — integration-тир; здесь фиксируется wiring-контракт
и graceful-ветка без otel.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.infrastructure.workflow.temporal_backend import TemporalWorkflowBackend


@pytest.mark.asyncio
async def test_connect_passes_tracing_interceptor() -> None:
    """Client.connect получает TracingInterceptor (trace propagation)."""
    fake_connect = AsyncMock(return_value=MagicMock())
    with (
        patch("temporalio.client.Client.connect", new=fake_connect),
        patch(
            "src.backend.infrastructure.workflow.temporal_backend.build_temporal_data_converter"
        ),
    ):
        backend = await TemporalWorkflowBackend.connect(
            target="localhost:7233", namespace="default", default_task_queue="q"
        )

    assert backend is not None
    fake_connect.assert_awaited_once()
    kwargs = fake_connect.await_args.kwargs
    interceptors = kwargs.get("interceptors") or []
    assert len(interceptors) == 1
    assert type(interceptors[0]).__name__ == "TracingInterceptor"


@pytest.mark.asyncio
async def test_connect_without_otel_graceful() -> None:
    """Отсутствие otel → connect проходит без interceptor (graceful)."""
    fake_client = MagicMock()
    fake_connect = AsyncMock(return_value=fake_client)

    def _fake_get_tracer(_name: str) -> Any:
        raise ImportError("otel unavailable")

    with (
        patch("temporalio.client.Client.connect", new=fake_connect),
        patch(
            "src.backend.infrastructure.workflow.temporal_backend.build_temporal_data_converter"
        ),
        patch("opentelemetry.trace.get_tracer", side_effect=_fake_get_tracer),
    ):
        backend = await TemporalWorkflowBackend.connect(
            target="localhost:7233", namespace="default", default_task_queue="q"
        )

    assert backend is not None
    kwargs = fake_connect.await_args.kwargs
    assert kwargs.get("interceptors") in ([], None)
