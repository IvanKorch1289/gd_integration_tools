"""Tests for ConfigHotReloader."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.backend.core.config.hot_reload import ConfigHotReloader, get_hot_reloader


class TestConfigHotReloader:
    def test_watch_adds_path(self) -> None:
        rel = ConfigHotReloader()
        rel.watch("/home/user/test/config.yml")
        assert Path("/home/user/test/config.yml") in rel._paths

    def test_watch_makes_relative_path_absolute(self) -> None:
        """ADR-0372: watcher не должен зависеть от текущего каталога."""
        rel = ConfigHotReloader()
        rel.watch("config_profiles")
        assert all(path.is_absolute() for path in rel._paths)

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
    async def test_trigger_reload_without_callbacks_reports_failure(self) -> None:
        """Без зарегистрированных callback'ов reload — ошибка, а не успех (ADR-0372)."""
        rel = ConfigHotReloader()
        result = await rel.trigger_reload()
        assert result["succeeded"] == 0
        assert result["failed"], "Отсутствие callback'ов должно попадать в failed"
        assert result["ok"] is False

    @pytest.mark.asyncio
    async def test_trigger_reload_reports_callbacks_count(self) -> None:
        """Отчёт содержит число зарегистрированных callback'ов."""
        rel = ConfigHotReloader()
        rel.on_reload(lambda: None)
        result = await rel.trigger_reload()
        assert result["callbacks"] == 1
        assert result["ok"] is True

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
        task = asyncio.create_task(asyncio.sleep(0.01))
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


class _FakeAwatch:
    """Имитация ``watchfiles.awatch`` с честной семантикой «потери событий».

    Событие, случившееся ДО того как watch « armed» (генератор запущен и
    OS-подписка установлена), теряется — как в реальном ``watchfiles``:
    rust-notify не видит изменений, произошедших до установки подписки.
    """

    def __init__(self) -> None:
        self.armed = False
        self.lost: list[set[str]] = []
        self.seen: list[set[str]] = []
        self._pending: list[set[str]] = []
        self.kwargs: dict[str, Any] = {}

    def emit(self, event: set[str]) -> None:
        """Эмулирует изменение в файловой системе.

        Args:
            event: Набор изменений (как отдаёт ``watchfiles``).

        Returns:
            None.

        """
        if not self.armed:
            self.lost.append(event)
            return
        self._pending.append(event)

    def __call__(self, *paths: str, **kwargs: Any) -> AsyncIterator[set[str]]:
        """Возвращает async-генератор с событиями (как ``awatch``)."""
        self.kwargs = kwargs

        async def _gen() -> AsyncIterator[set[str]]:
            self.armed = True
            while True:
                await asyncio.sleep(0.01)
                if self._pending:
                    batch = self._pending.pop(0)
                    self.seen.append(batch)
                    yield batch

        return _gen()


class TestWatcherArming:
    """Watcher подписывается на ФС до возврата из ``start()`` (ADR-0379)."""

    @pytest.mark.asyncio
    async def test_change_right_after_start_is_not_lost(self, tmp_path: Path) -> None:
        """Изменение в том же тике, что и ``start()``, не должно теряться.

        Регрессия: ``create_task`` не запускает watcher немедленно, поэтому
        запись в файл сразу после ``start()`` попадала в никуда
        (events=0). Фикс — ``await asyncio.sleep(0)`` в ``start()``.
        """
        fake = _FakeAwatch()
        reloader = ConfigHotReloader()
        reloader.watch(tmp_path)

        with patch.dict(sys.modules, {"watchfiles": SimpleNamespace(awatch=fake)}):
            await reloader.start()
            fake.emit({("config.yml", "modify")})
            for _ in range(100):
                await asyncio.sleep(0.01)
                if fake.seen:
                    break
            await reloader.stop()

        assert fake.lost == [], (
            "Событие потеряно: watcher не успел подписаться на ФС к моменту "
            "возврата из start()"
        )
        assert fake.seen, "Watcher не увидел изменение файла"

    @pytest.mark.asyncio
    async def test_watchfiles_receives_debounce_and_step(self, tmp_path: Path) -> None:
        """``debounce_ms`` управляет ОКНОМ группировки, а не периодом опроса.

        Регрессия: значение передавалось в ``step`` watchfiles, а
        ``debounce`` оставался 1600 мс — имя параметра не соответствовало
        поведению.
        """
        fake = _FakeAwatch()
        reloader = ConfigHotReloader(debounce_ms=750)
        reloader.watch(tmp_path)

        with patch.dict(sys.modules, {"watchfiles": SimpleNamespace(awatch=fake)}):
            await reloader.start()
            await asyncio.sleep(0)
            await reloader.stop()

        assert fake.kwargs.get("debounce") == 750
        assert fake.kwargs.get("step") is not None
        assert fake.kwargs["step"] != 750


class TestReloadReportHonesty:
    """Отчёт ``settings.reload()`` с ``failed`` — это ОШИБКА (ADR-0379)."""

    @pytest.mark.asyncio
    async def test_callback_fails_when_reload_report_has_failures(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``failed`` из ``settings.reload()`` попадает в ``failed`` отчёта."""
        from src.backend.core.config import settings as settings_mod
        from src.backend.core.config.hot_reload import register_settings_reload_callback

        class _FakeSettings:
            """Настройки, у которых reload сообщает об ошибке."""

            def reload(self) -> dict[str, Any]:
                """Возвращает отчёт с ошибкой перезагрузки.

                Returns:
                    Отчёт ``reloaded``/``failed`` с одной ошибкой.

                """
                return {
                    "reloaded": [],
                    "failed": [{"name": "app", "error": "broken yaml"}],
                }

        monkeypatch.setattr(settings_mod, "settings", _FakeSettings())

        reloader = ConfigHotReloader()
        register_settings_reload_callback(reloader)
        report = await reloader.trigger_reload(reason="test")

        assert report["ok"] is False
        assert report["succeeded"] == 0
        assert report["failed"], "Непустой failed из reload() — это ошибка"
        assert report["failed"][0]["failed"][0]["name"] == "app"

    @pytest.mark.asyncio
    async def test_callback_succeeds_on_clean_report(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Пустой ``failed`` — успех (регрессия-контроль к fail-closed)."""
        from src.backend.core.config import settings as settings_mod
        from src.backend.core.config.hot_reload import register_settings_reload_callback

        class _FakeSettings:
            """Настройки, у которых reload проходит без ошибок."""

            def reload(self) -> dict[str, Any]:
                """Возвращает успешный отчёт перезагрузки.

                Returns:
                    Отчёт без ошибок.

                """
                return {"reloaded": ["app"], "failed": []}

        monkeypatch.setattr(settings_mod, "settings", _FakeSettings())

        reloader = ConfigHotReloader()
        register_settings_reload_callback(reloader)
        report = await reloader.trigger_reload(reason="test")

        assert report["ok"] is True
        assert report["succeeded"] == 1
        assert report["failed"] == []


class TestRestartRequiredWarning:
    """ADR-0400: hot-reload не применяет параметры пулов БД — нужен рестарт."""

    @pytest.mark.asyncio
    async def test_report_lists_db_pool_sections_requiring_restart(self) -> None:
        """Отчёт reload содержит секции, применяемые только после рестарта."""
        reloader = ConfigHotReloader()
        reloader.on_reload(lambda: None)

        report = await reloader.trigger_reload(reason="test")

        restart_required = report["restart_required"]
        assert "database.*" in restart_required
        assert "external_databases.*" in restart_required

    @pytest.mark.asyncio
    async def test_report_contains_warning_about_db_pools(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """В лог уходит явное предупреждение про рестарт для пулов БД."""
        reloader = ConfigHotReloader()
        reloader.on_reload(lambda: None)

        with caplog.at_level("WARNING"):
            await reloader.trigger_reload(reason="test")

        messages = [rec.message for rec in caplog.records]
        assert any(
            "database.*" in message and "external_databases.*" in message
            for message in messages
        ), f"Нет предупреждения о пулах БД: {messages}"

    @pytest.mark.asyncio
    async def test_report_without_callbacks_also_lists_restart_sections(self) -> None:
        """Даже при ошибке reload отчёт содержит список секций для рестарта."""
        reloader = ConfigHotReloader()

        report = await reloader.trigger_reload(reason="test")

        assert "database.*" in report["restart_required"]
