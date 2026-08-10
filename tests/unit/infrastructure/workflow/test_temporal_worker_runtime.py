"""D-A8-04 fix (cycle 1): unit-тесты TemporalWorkerRuntime + lifespan ops.

Все ``temporalio.*`` импорты мокаются через ``unittest.mock.patch`` —
SDK может отсутствовать в test env (lazy-import pattern).
"""


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
        from src.backend.infrastructure.workflow import temporal_worker_runtime as mod

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
                client=client, task_queue="test-queue", workflow_classes=[wf_cls],
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
        from src.backend.infrastructure.workflow import temporal_worker_runtime as mod

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
        from src.backend.infrastructure.workflow import temporal_worker_runtime as mod

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
        from src.backend.infrastructure.workflow import temporal_worker_runtime as mod

        runtime = mod.get_temporal_worker_runtime()
        await runtime.stop()
        await runtime.stop()
        assert not runtime.is_running

    @pytest.mark.asyncio
    async def test_double_start_raises(self) -> None:
        """Повторный start() без stop() → RuntimeError."""
        from src.backend.infrastructure.workflow import temporal_worker_runtime as mod

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
        from src.backend.infrastructure.workflow import temporal_worker_runtime as mod

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
        """workflow_use_temporal=True → worker стартует (TemporalClient mocked).

        D-A8-03 fix (cycle 1): activities=[] — ActivityBridge.decorate wire
        отдельно через composition layer (cross-layer concern).
        """
        from src.backend.infrastructure.workflow import temporal_worker_runtime as mod

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
        # D-A8-03 fix: activities=[] (ActivityBridge wire вне scope cycle 1)
        kwargs = fake_worker_mod.Worker.call_args.kwargs
        assert kwargs["activities"] == []


class TestTemporalWorkerPoolProductionWire:
    """D-AUDIT-808 fix (cycle 8): TemporalWorkerPool instantiated в production lifespan.

    DOMAIN-WF-P0-002 (cycle-4): ``TemporalWorkerPool`` (94 LOC) был
    defined but never instantiated в production — Worker создавался
    напрямую через ``runtime.start(client=...)`` (cycle 1 D-A8-04).
    Cycle-8 verify: добавить explicit ``TemporalWorkerPool.register_worker``
    в ``start_temporal_worker_runtime`` lifespan fn.
    """

    @pytest.mark.asyncio
    async def test_pool_actually_instantiated_in_lifespan(self) -> None:
        """Production lifespan создаёт TemporalWorkerPool + register_worker.

        До cycle-8: pool не создавался. После: pool.register_worker() вызван,
        runtime.bind_pool() связан, runtime._pool is not None.
        """
        from src.backend.infrastructure.workflow import temporal_worker_runtime as mod

        fake_worker_mod, _ = _patch_temporalio()
        fake_factory = MagicMock()
        fake_client = MagicMock()
        fake_factory.get_client = AsyncMock(return_value=fake_client)
        fake_factory._cache = {}  # Mutable для pre-seed проверки

        fake_flags = MagicMock()
        fake_flags.workflow_use_temporal = True

        pool_instance = MagicMock(name="TemporalWorkerPool-instance")
        pool_instance._workers = {"q1": MagicMock(name="worker")}
        task = MagicMock(name="task")
        task.done = MagicMock(return_value=False)
        pool_instance._tasks = {"q1": task}
        pool_instance.list_workers = MagicMock(return_value=["q1"])
        pool_instance.register_worker = AsyncMock()
        pool_instance.shutdown = AsyncMock()

        with patch(
            "src.backend.core.config.features.FeatureFlags",
            return_value=fake_flags,
        ), patch(
            "src.backend.infrastructure.workflow.temporal_client.TemporalClientFactory",
            return_value=fake_factory,
        ), patch(
            "src.backend.infrastructure.workflow.temporal_client.TemporalWorkerPool",
            return_value=pool_instance,
        ), patch.dict(
            "sys.modules",
            {
                "temporalio.worker": fake_worker_mod,
                "temporalio.opentelemetry": MagicMock(),
            },
        ):
            await mod.start_temporal_worker_runtime()

        # D-AUDIT-808 verify: pool реально instantiated + register_worker вызван.
        pool_instance.register_worker.assert_awaited_once()
        runtime = mod.get_temporal_worker_runtime()
        assert runtime._pool is pool_instance, (
            "TemporalWorkerPool должен быть привязан к runtime через bind_pool"
        )
        assert runtime.is_running is True
        # Pre-seed: factory._cache[namespace] заполнен подключённым client'ом
        # чтобы register_worker не переподключался.
        assert fake_factory._cache, "factory cache должен быть pre-seed"

    @pytest.mark.asyncio
    async def test_pool_shutdown_in_lifespan_stop(self) -> None:
        """stop_temporal_worker_runtime закрывает TemporalWorkerPool.shutdown()."""
        from src.backend.infrastructure.workflow import temporal_worker_runtime as mod

        runtime = mod.get_temporal_worker_runtime()
        # Симулируем production-bind: pool+worker+task.
        pool = MagicMock(name="pool")
        pool.shutdown = AsyncMock()
        worker = MagicMock(name="worker")
        task = MagicMock(name="task")
        task.done = MagicMock(return_value=False)
        pool._workers = {"q1": worker}
        pool._tasks = {"q1": task}
        runtime._pool = pool
        runtime._worker = worker
        runtime._task = task
        runtime._task_queue = "q1"

        await mod.stop_temporal_worker_runtime()

        pool.shutdown.assert_awaited_once()
        assert runtime._pool is None
        assert runtime._worker is None
        assert runtime._task is None
        assert not runtime.is_running

    @pytest.mark.asyncio
    async def test_stop_without_pool_uses_legacy_runtime_stop(self) -> None:
        """Unit-test path (single-client runtime.start) — fallback на runtime.stop()."""
        from src.backend.infrastructure.workflow import temporal_worker_runtime as mod

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
            assert runtime._pool is None, "single-client path: _pool остаётся None"
            await mod.stop_temporal_worker_runtime()

        assert not runtime.is_running
