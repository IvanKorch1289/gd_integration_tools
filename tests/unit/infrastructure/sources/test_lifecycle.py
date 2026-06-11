"""Unit-тесты для ``src.backend.infrastructure.sources._lifecycle``."""

# ruff: noqa: S101

from __future__ import annotations

import asyncio
import logging

import pytest

from src.backend.infrastructure.sources import _lifecycle as lifecycle


@pytest.mark.unit
class TestGracefulCancel:
    @pytest.mark.asyncio
    async def test_none_task_is_noop(self) -> None:
        await lifecycle.graceful_cancel(None, source_id="s1")

    @pytest.mark.asyncio
    async def test_already_done_task_is_noop(self) -> None:
        async def done_immediately() -> None:
            pass

        task = asyncio.create_task(done_immediately())
        await task
        await lifecycle.graceful_cancel(task, source_id="s2")
        assert task.done()

    @pytest.mark.asyncio
    async def test_cancelled_error_swallowed(self) -> None:
        async def sleep_forever() -> None:
            await asyncio.sleep(0.1)

        task = asyncio.create_task(sleep_forever())
        await asyncio.sleep(0)  # даём event loop запустить корутину
        await lifecycle.graceful_cancel(task, source_id="s3")

        assert task.cancelled()

    @pytest.mark.asyncio
    async def test_other_exception_logged(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        async def raise_value_error() -> None:
            try:
                await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                raise ValueError("boom")

        task = asyncio.create_task(raise_value_error())
        await asyncio.sleep(0)

        with caplog.at_level(
            logging.WARNING, logger="infrastructure.sources.lifecycle"
        ):
            await lifecycle.graceful_cancel(task, source_id="s4")

        assert task.done()
        assert "boom" in caplog.text
        assert "s4" in caplog.text
