"""Unit tests for src.backend.services.sources.lifecycle."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.core.config.source_spec import SourceSpec
from src.backend.core.interfaces.invoker import InvocationMode
from src.backend.core.interfaces.source import SourceKind
from src.backend.services.sources.lifecycle import (
    _safe_stop,
    start_all_sources,
    stop_all_sources,
)


def _fake_spec(
    source_id: str = "wh-1",
    action: str = "orders.pay",
    idempotency: bool = True,
    mode: InvocationMode = InvocationMode.SYNC,
    reply_channel: str | None = None,
) -> SourceSpec:
    return SourceSpec(
        id=source_id,
        kind=SourceKind.WEBHOOK,
        action=action,
        mode=mode,
        idempotency=idempotency,
        reply_channel=reply_channel,
    )


def _fake_source(source_id: str) -> MagicMock:
    source = MagicMock()
    source.source_id = source_id
    source.kind = SourceKind.WEBHOOK
    source.start = AsyncMock()
    source.stop = AsyncMock()
    return source


@pytest.mark.asyncio
class TestStartAllSources:
    async def test_success(self) -> None:
        registry = MagicMock()
        source = _fake_source("wh-1")
        registry.get = MagicMock(return_value=source)
        invoker = MagicMock()
        spec = _fake_spec("wh-1")
        await start_all_sources(
            registry=registry, invoker=invoker, specs=[spec]
        )
        registry.get.assert_called_once_with("wh-1")
        source.start.assert_awaited_once()
        # adapter.handle is passed as callback
        assert callable(source.start.await_args[0][0])

    async def test_missing_source_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        registry = MagicMock()
        registry.get = MagicMock(side_effect=KeyError("missing"))
        invoker = MagicMock()
        spec = _fake_spec("wh-1")
        with caplog.at_level("WARNING"):
            await start_all_sources(
                registry=registry, invoker=invoker, specs=[spec]
            )
        assert "не в реестре" in caplog.text
        registry.get.assert_called_once_with("wh-1")

    async def test_start_exception(self, caplog: pytest.LogCaptureFixture) -> None:
        registry = MagicMock()
        source = _fake_source("wh-1")
        source.start = AsyncMock(side_effect=RuntimeError("boom"))
        registry.get = MagicMock(return_value=source)
        invoker = MagicMock()
        spec = _fake_spec("wh-1")
        with caplog.at_level("ERROR"):
            await start_all_sources(
                registry=registry, invoker=invoker, specs=[spec]
            )
        assert "start failed" in caplog.text

    async def test_idempotency_disabled(self) -> None:
        registry = MagicMock()
        source = _fake_source("wh-1")
        registry.get = MagicMock(return_value=source)
        invoker = MagicMock()
        dedupe = MagicMock()
        spec = _fake_spec("wh-1", idempotency=False)
        await start_all_sources(
            registry=registry, invoker=invoker, specs=[spec], dedupe=dedupe
        )
        # adapter created without dedupe — callback should work
        source.start.assert_awaited_once()

    async def test_reply_channel_passed(self) -> None:
        registry = MagicMock()
        source = _fake_source("wh-1")
        registry.get = MagicMock(return_value=source)
        invoker = MagicMock()
        spec = _fake_spec("wh-1", reply_channel="ch1", mode=InvocationMode.ASYNC_QUEUE)
        await start_all_sources(
            registry=registry, invoker=invoker, specs=[spec]
        )
        source.start.assert_awaited_once()


@pytest.mark.asyncio
class TestStopAllSources:
    async def test_stop_all(self) -> None:
        registry = MagicMock()
        s1 = _fake_source("a")
        s2 = _fake_source("b")
        registry.all = MagicMock(return_value=(s1, s2))
        await stop_all_sources(registry)
        s1.stop.assert_awaited_once()
        s2.stop.assert_awaited_once()

    async def test_stop_exception(self, caplog: pytest.LogCaptureFixture) -> None:
        registry = MagicMock()
        s1 = _fake_source("a")
        s1.stop = AsyncMock(side_effect=RuntimeError("err"))
        registry.all = MagicMock(return_value=(s1,))
        with caplog.at_level("WARNING"):
            await stop_all_sources(registry)
        assert "stop failed" in caplog.text


@pytest.mark.asyncio
class TestSafeStop:
    async def test_success(self) -> None:
        coro = AsyncMock()
        await _safe_stop("src-1", coro())
        coro.assert_awaited_once()

    async def test_exception(self, caplog: pytest.LogCaptureFixture) -> None:
        async def bad() -> None:
            raise RuntimeError("x")

        with caplog.at_level("WARNING"):
            await _safe_stop("src-1", bad())
        assert "stop failed" in caplog.text
