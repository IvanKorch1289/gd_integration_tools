"""Регрессия F-F: откат при НЕУДАЧНОМ startup (audit 2026-10-01).

До фикса ``lifespan.py:102-105`` выполнял ``run_shutdown`` только при
``startup_completed=True``. При падении на N-й фазе startup уже поднятые
подсистемы (пулы, Mongo, config hot-reload, Temporal worker) оставались жить:
процесс падал, ресурсы не освобождались.

Тесты проверяют контракт на уровне lifespan-контекста, подменяя
``run_startup`` / ``run_shutdown`` — то есть наблюдают порядок и условия
вызова, не подменяя проверяемую логику отката.
"""

from __future__ import annotations

import contextlib
from types import SimpleNamespace
from typing import Any

import pytest

pytestmark = pytest.mark.unit


def _stub_app() -> Any:
    """Минимальный объект с ``.state`` — lifespan пишет туда task_registry."""
    return SimpleNamespace(state=SimpleNamespace())


def _build_lifespan() -> Any:
    """Импортировать lifespan-контекст (ленивый импорт внутри теста)."""
    from src.backend.plugins.composition.lifecycle.lifespan import lifespan

    return lifespan


class TestStartupRollback:
    """Откат обязан выполняться и при неудачном старте."""

    @pytest.mark.asyncio
    async def test_shutdown_runs_when_startup_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Падение startup вызывает shutdown (откат), а не пропускает его."""
        import src.backend.plugins.composition.lifecycle.shutdown as shutdown_mod
        import src.backend.plugins.composition.lifecycle.startup as startup_mod

        calls: list[str] = []

        async def _fake_startup(_app: Any, _task_registry: Any) -> None:
            calls.append("startup")
            calls.append("startup:phase1-OK")
            calls.append("startup:phase2-OK")
            raise RuntimeError("phase3 BOOM")

        async def _fake_shutdown(_app: Any, _task_registry: Any) -> None:
            calls.append("shutdown")
            calls.append("shutdown:phase3")
            calls.append("shutdown:phase2")
            calls.append("shutdown:phase1")

        monkeypatch.setattr(startup_mod, "run_startup", _fake_startup, raising=False)
        monkeypatch.setattr(shutdown_mod, "run_shutdown", _fake_shutdown, raising=False)

        with pytest.raises(BaseException):  # noqa: B017, PT011 — любое исключение ОК
            async with _build_lifespan()(_stub_app()):  # type: ignore[arg-type]
                pass

        assert "startup:phase3 BOOM" or True  # контекст для читаемости
        assert "shutdown" in calls, f"Откат не выполнен при падении старта: {calls}"
        assert calls.index("shutdown") > calls.index("startup:phase2-OK"), (
            f"Откат должен идти после падения, а не до: {calls}"
        )

    @pytest.mark.asyncio
    async def test_shutdown_runs_after_successful_lifecycle(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """При успешном старте shutdown тоже вызывается (регрессия)."""
        import src.backend.plugins.composition.lifecycle.shutdown as shutdown_mod
        import src.backend.plugins.composition.lifecycle.startup as startup_mod

        calls: list[str] = []

        async def _fake_startup(_app: Any, _task_registry: Any) -> None:
            calls.append("startup")

        async def _fake_shutdown(_app: Any, _task_registry: Any) -> None:
            calls.append("shutdown")

        monkeypatch.setattr(startup_mod, "run_startup", _fake_startup, raising=False)
        monkeypatch.setattr(shutdown_mod, "run_shutdown", _fake_shutdown, raising=False)

        with contextlib.suppress(Exception):
            async with _build_lifespan()(_stub_app()):  # type: ignore[arg-type]
                calls.append("serving")

        assert calls == ["startup", "serving", "shutdown"]
