"""D-A8-04 fix (cycle 1): unit-тесты TemporalWorkerRuntime + lifespan ops.

Все ``temporalio.*`` импорты мокаются через ``unittest.mock.patch`` —
SDK может отсутствовать в test env (lazy-import pattern).
"""

# ruff: noqa: S101

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.core.workflow_registry import workflow_registry


@pytest.fixture(autouse=True)
def _reset_state() -> None:
    """Сбрасывает singleton runtime + registry между тестами."""
    from src.backend.infrastructure.workflow import temporal_worker_runtime as mod

    mod.reset_temporal_worker_runtime()
    workflow_registry.clear()
    yield
    mod.reset_temporal_worker_runtime()
    workflow_registry.clear()


def _make_workflow_class(name: str = "FakeWorkflow") -> type:
    """Workflow-класс, проходящий ``workflow_registry._is_workflow_class``."""
    cls = type(name, (), {"_is_workflow": True})
    return cls


def _patch_temporalio() -> tuple[MagicMock, MagicMock]:
    """Подменяет ``temporalio.worker.Worker`` и OTel interceptor."""
    worker_instance = MagicMock(name="Worker-instance")
    worker_instance.shutdown = AsyncMock(return_value=None)
    worker_instance.run = MagicMock(return_value=MagicMock())

    worker_cls = MagicMock(return_value=worker_instance)
    worker_cls.__name__ = "Worker"

    fake_temporalio_worker = MagicMock()
    fake_temporalio_worker.Worker = worker_cls

    return fake_temporalio_worker, worker_instance


class TestTemporalWorkerRuntimeCreation:
    """D-A8-04 fix (cycle 1): composition + start."""

    @pytest.mark.asyncio
    async def test_worker_creation_with_classes(self) -> None:
        """Worker создаётся + регистрируется в TaskRegistry при start()."""
        from src.backend.infrastructure.workflow import (
            temporal_worker_runtime as mod,
        )

        fake_worker_mod, _worker_instance = _patch_temporalio()
        wf_cls = _make_workflow_class("W1")
        workflow_registry.register(wf_cls)

        runtime = mod.get_temporal_worker_runtime()
        client = MagicMock()

        with patch.dict(
            "sys.modules",
            {
                "temporalio.worker": fake_worker_mod,
                "temporalio.opentelemetry": MagicMock(),
            },
        ):
            await runtime.start(
                client=client, task_queue="test-queue", workflow_classes=[wf_cls]
            )

        assert runtime.is_running is True
        assert runtime.task_queue == "test-queue"
        fake_worker_mod.Worker.assert_called_once()
        kwargs = fake_worker_mod.Worker.call_args.kwargs
        assert kwargs["task_queue"] == "test-queue"
        assert kwargs["workflows"] == [wf_cls]

    @pytest.mark.asyncio
    async def test_worker_creation_no_classes_skips_registration(self) -> None:
        """Worker создаётся даже без workflow-классов (warning, не raise)."""
        from src.backend.infrastructure.workflow import (
            temporal_worker_runtime as mod,
        )

        fake_worker_mod, _ = _patch_temporalio()

        runtime = mod.get_temporal_worker_runtime()
        with patch.dict(
            "sys.modules",
            {
                "temporalio.worker": fake_worker_mod,
                "temporalio.opentelemetry": MagicMock(),
            },
        ):
            await runtime.start(
                client=MagicMock(),
                task_queue="q",
                workflow_classes=[],
            )

        assert runtime.is_running is True
        kwargs = fake_worker_mod.Worker.call_args.kwargs
        assert kwargs["workflows"] == []

    @pytest.mark.asyncio
    async def test_start_stop_lifecycle(self) -> None:
        """start() → stop() корректно очищает state + отменяет task."""
        from src.backend.infrastructure.workflow import (
            temporal_worker_runtime as mod,
        )

        fake_worker_mod, worker_instance = _patch_temporalio()
        runtime = mod.get_temporal_worker_runtime()

        with patch.dict(
            "sys.modules",
            {
                "temporalio.worker": fake_worker_mod,
                "temporalio.opentelemetry": MagicMock(),
            },
        ):
            await runtime.start(client=MagicMock(), task_queue="q")
            assert runtime.is_running

            await runtime.stop()
            assert not runtime.is_running
            assert runtime.task_queue is None

        worker_instance.shutdown.assert_awaited()

    @pytest.mark.asyncio
    async def test_stop_is_idempotent(self) -> None:
        """stop() без активного worker'а — no-op, без ошибок."""
        from src.backend.infrastructure.workflow import (
            temporal_worker_runtime as mod,
        )

        runtime = mod.get_temporal_worker_runtime()
        await runtime.stop()
        await runtime.stop()
        assert not runtime.is_running

    @pytest.mark.asyncio
    async def test_double_start_raises(self) -> None:
        """Повторный start() без stop() → RuntimeError."""
        from src.backend.infrastructure.workflow import (
            temporal_worker_runtime as mod,
        )

        fake_worker_mod, _ = _patch_temporalio()
        runtime = mod.get_temporal_worker_runtime()

        with patch.dict(
            "sys.modules",
            {
                "temporalio.worker": fake_worker_mod,
                "temporalio.opentelemetry": MagicMock(),
            },
        ):
            await runtime.start(client=MagicMock(), task_queue="q")
            with pytest.raises(RuntimeError, match="уже запущен"):
                await runtime.start(client=MagicMock(), task_queue="q")


class TestStartTemporalWorkerRuntimeFeatureFlag:
    """D-A8-04 fix (cycle 1): feature-flag guard в lifespan-op."""

    @pytest.mark.asyncio
    async def test_feature_flag_disabled_skips_start(self) -> None:
        """workflow_use_temporal=False → op no-op'ит (start не вызывается)."""
        from src.backend.infrastructure.workflow import (
            temporal_worker_runtime as mod,
        )

        fake_flags = MagicMock()
        fake_flags.workflow_use_temporal = False

        with patch(
            "src.backend.core.config.features.FeatureFlags",
            return_value=fake_flags,
        ):
            await mod.start_temporal_worker_runtime()

        runtime = mod.get_temporal_worker_runtime()
        assert not runtime.is_running

    @pytest.mark.asyncio
    async def test_feature_flag_enabled_starts_worker(self) -> None:
        """workflow_use_temporal=True → worker стартует (TemporalClient mocked)."""
        from src.backend.infrastructure.workflow import (
            temporal_worker_runtime as mod,
        )

        fake_worker_mod, _ = _patch_temporalio()
        fake_factory = MagicMock()
        fake_client = MagicMock()
        fake_factory.get_client = AsyncMock(return_value=fake_client)

        fake_flags = MagicMock()
        fake_flags.workflow_use_temporal = True

        with patch(
            "src.backend.core.config.features.FeatureFlags",
            return_value=fake_flags,
        ), patch(
            "src.backend.infrastructure.workflow.temporal_client.TemporalClientFactory",
            return_value=fake_factory,
        ), patch.dict(
            "sys.modules",
            {
                "temporalio.worker": fake_worker_mod,
                "temporalio.opentelemetry": MagicMock(),
            },
        ):
            await mod.start_temporal_worker_runtime()

        runtime = mod.get_temporal_worker_runtime()
        assert runtime.is_running
        fake_factory.get_client.assert_awaited()
