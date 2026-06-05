"""Unit-tests for outbox lifecycle hooks."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.infrastructure.messaging.outbox.lifecycle import (
    _resolve_state,
    start_outbox_dispatcher,
    stop_outbox_dispatcher,
)


@pytest.fixture(autouse=True)
def _enable_outbox(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_settings = MagicMock()
    fake_settings.enabled = True
    fake_settings.poll_interval_seconds = 1.0
    fake_settings.batch_size = 10
    fake_settings.max_retries = 3
    fake_settings.retry_backoff_seconds = 1.0
    fake_settings.shutdown_timeout_seconds = 5.0
    monkeypatch.setattr(
        "src.backend.infrastructure.messaging.outbox.lifecycle.outbox_settings",
        fake_settings,
    )


@pytest.fixture
def fake_app() -> SimpleNamespace:
    return SimpleNamespace(state=SimpleNamespace())


@pytest.mark.asyncio
async def test_start_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.backend.infrastructure.messaging.outbox.lifecycle.outbox_settings.enabled",
        False,
    )
    app = SimpleNamespace(state=SimpleNamespace())
    await start_outbox_dispatcher(app)


@pytest.mark.asyncio
async def test_start_no_state_namespace() -> None:
    await start_outbox_dispatcher(None)


@pytest.mark.asyncio
async def test_start_already_started(fake_app: SimpleNamespace) -> None:
    fake_app.state.outbox_dispatcher = MagicMock()
    await start_outbox_dispatcher(fake_app)


@pytest.mark.asyncio
async def test_start_missing_dependencies(fake_app: SimpleNamespace) -> None:
    await start_outbox_dispatcher(fake_app)
    assert getattr(fake_app.state, "outbox_dispatcher", None) is None


@pytest.mark.asyncio
async def test_start_success(fake_app: SimpleNamespace) -> None:
    mock_dispatcher = MagicMock()
    mock_dispatcher.start = AsyncMock()
    with patch(
        "src.backend.infrastructure.messaging.outbox.lifecycle.OutboxDispatcher",
        return_value=mock_dispatcher,
    ):
        await start_outbox_dispatcher(
            fake_app,
            backend=MagicMock(),
            pending_source=AsyncMock(),
            ack=AsyncMock(),
            deliverer=AsyncMock(),
        )
    mock_dispatcher.start.assert_awaited_once()
    assert fake_app.state.outbox_dispatcher is mock_dispatcher


@pytest.mark.asyncio
async def test_stop_no_state() -> None:
    await stop_outbox_dispatcher(None)


@pytest.mark.asyncio
async def test_stop_not_started(fake_app: SimpleNamespace) -> None:
    await stop_outbox_dispatcher(fake_app)


@pytest.mark.asyncio
async def test_stop_graceful(fake_app: SimpleNamespace) -> None:
    mock_dispatcher = MagicMock()
    mock_dispatcher.stop = AsyncMock()
    fake_app.state.outbox_dispatcher = mock_dispatcher
    await stop_outbox_dispatcher(fake_app)
    mock_dispatcher.stop.assert_awaited_once()
    assert fake_app.state.outbox_dispatcher is None


def test_resolve_state_fastapi_style() -> None:
    app = SimpleNamespace(state=SimpleNamespace(foo=1))
    assert _resolve_state(app) is app.state


def test_resolve_state_plain() -> None:
    app = SimpleNamespace(foo=1)
    assert _resolve_state(app) is app


def test_resolve_state_none() -> None:
    assert _resolve_state(None) is None
