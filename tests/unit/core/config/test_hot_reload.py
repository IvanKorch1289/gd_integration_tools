"""Tests for ConfigHotReloader."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.backend.core.config.hot_reload import ConfigHotReloader, get_hot_reloader


class TestConfigHotReloader:
    def test_watch_adds_path(self) -> None:
        rel = ConfigHotReloader()
        rel.watch("/home/user/test/config.yml")
        assert Path("/home/user/test/config.yml") in rel._paths

    def test_on_reload_registers_callback(self) -> None:
        rel = ConfigHotReloader()

        def cb() -> None:
            pass

        rel.on_reload(cb)
        assert rel._callbacks == [cb]

    @pytest.mark.asyncio
    async def test_trigger_reload_sync_callback(self) -> None:
        rel = ConfigHotReloader()
        called = False

        def cb() -> None:
            nonlocal called
            called = True

        rel.on_reload(cb)
        result = await rel.trigger_reload()
        assert called is True
        assert result["succeeded"] == 1
        assert result["failed"] == []

    @pytest.mark.asyncio
    async def test_trigger_reload_async_callback(self) -> None:
        rel = ConfigHotReloader()
        called = False

        async def cb() -> None:
            nonlocal called
            called = True

        rel.on_reload(cb)
        result = await rel.trigger_reload()
        assert called is True
        assert result["succeeded"] == 1

    @pytest.mark.asyncio
    async def test_trigger_reload_exception_captured(self) -> None:
        rel = ConfigHotReloader()

        def bad() -> None:
            raise RuntimeError("boom")

        rel.on_reload(bad)
        result = await rel.trigger_reload()
        assert result["succeeded"] == 0
        assert len(result["failed"]) == 1
        assert "boom" in result["failed"][0]["error"]

    @pytest.mark.asyncio
    async def test_start_skips_when_already_running(self) -> None:
        rel = ConfigHotReloader()
        mock_task = MagicMock()
        mock_task.done.return_value = False
        rel._task = mock_task
        with patch.object(rel, "_watch_loop", return_value=None):
            await rel.start()
        mock_task.done.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_disabled_in_prod(self) -> None:
        rel = ConfigHotReloader()
        with (
            patch("src.backend.core.config.profile.get_active_profile") as prof,
            patch("src.backend.core.config.features.feature_flags") as ff,
        ):
            prof.return_value.value = "prod"
            ff.prod_hot_reload_disable = True
            await rel.start()
        assert rel._task is None

    @pytest.mark.asyncio
    async def test_start_spawns_task(self) -> None:
        rel = ConfigHotReloader()
        rel.watch("/home/user/test")
        registry = MagicMock()
        registry.create_task = MagicMock(return_value=MagicMock())
        with (
            patch(
                "src.backend.core.config.hot_reload.get_task_registry",
                return_value=registry,
            ),
            patch("src.backend.core.config.profile.get_active_profile") as prof,
            patch("src.backend.core.config.features.feature_flags") as ff,
            patch("pathlib.Path.exists", return_value=True),
        ):
            prof.return_value.value = "dev"
            ff.prod_hot_reload_disable = False
            await rel.start()
        registry.create_task.assert_called_once()
        assert rel._task is not None

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self) -> None:
        rel = ConfigHotReloader()
        task = asyncio.create_task(asyncio.sleep(10))
        rel._task = task
        await rel.stop()
        assert task.cancelled() or task.done()

    @pytest.mark.asyncio
    async def test_watch_loop_no_watchfiles(self) -> None:
        rel = ConfigHotReloader()
        rel.watch("/home/user/test")
        with (
            patch("src.backend.core.config.profile.get_active_profile") as prof,
            patch("src.backend.core.config.features.feature_flags") as ff,
            patch("pathlib.Path.exists", return_value=True),
        ):
            prof.return_value.value = "dev"
            ff.prod_hot_reload_disable = False
            with patch.dict("sys.modules", {"watchfiles": None}):
                await rel._watch_loop()

    @pytest.mark.asyncio
    async def test_watch_loop_no_paths(self) -> None:
        rel = ConfigHotReloader()
        with patch("pathlib.Path.exists", return_value=False):
            await rel._watch_loop()


class TestGetHotReloader:
    def test_singleton(self) -> None:
        r1 = get_hot_reloader()
        r2 = get_hot_reloader()
        assert r1 is r2
