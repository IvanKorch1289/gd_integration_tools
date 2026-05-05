# ruff: noqa: S101
"""Тесты `create_workflow_backend` factory (Wave D.2)."""

from __future__ import annotations

import pytest

from src.core.workflow import FakeWorkflowBackend, WorkflowBackend
from src.infrastructure.workflow.factory import create_workflow_backend


@pytest.mark.asyncio
class TestCreateWorkflowBackend:
    async def test_fake_kind(self) -> None:
        backend = await create_workflow_backend(kind="fake")
        assert isinstance(backend, FakeWorkflowBackend)
        assert isinstance(backend, WorkflowBackend)

    async def test_pg_runner_kind(self) -> None:
        backend = await create_workflow_backend(kind="pg_runner")
        # Не делаем isinstance — adapter лежит в infrastructure;
        # достаточно проверки runtime-checkable Protocol.
        assert isinstance(backend, WorkflowBackend)

    async def test_auto_dev_light_picks_pg_runner(self) -> None:
        backend = await create_workflow_backend(kind="auto", profile="dev_light")
        assert isinstance(backend, WorkflowBackend)
        # pg_runner adapter — конкретный класс из infrastructure/.
        from src.infrastructure.workflow.pg_runner_backend import (
            PgRunnerWorkflowBackend,
        )

        assert isinstance(backend, PgRunnerWorkflowBackend)

    async def test_auto_prod_falls_back_when_temporal_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Имитируем RuntimeError при попытке connect (нет SDK).
        async def _broken_connect(**kwargs: object) -> object:
            raise RuntimeError("temporalio SDK not installed.")

        import sys
        import types

        fake_module = types.ModuleType("src.infrastructure.workflow.temporal_backend")

        class _Shim:
            connect = staticmethod(_broken_connect)

        fake_module.TemporalWorkflowBackend = _Shim  # type: ignore[attr-defined]
        monkeypatch.setitem(
            sys.modules, "src.infrastructure.workflow.temporal_backend", fake_module
        )

        backend = await create_workflow_backend(kind="auto", profile="prod")
        from src.infrastructure.workflow.pg_runner_backend import (
            PgRunnerWorkflowBackend,
        )

        assert isinstance(backend, PgRunnerWorkflowBackend)

    async def test_unknown_kind_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown WorkflowBackend kind"):
            await create_workflow_backend(kind="bogus")
