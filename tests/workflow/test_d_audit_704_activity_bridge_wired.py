"""D-AUDIT-704 fix (cycle 7): wire ``ActivityBridge`` в production lifespan.

Без этого теста ``register_langgraph_checkpoint_activities`` остаётся
dead code (определена в ``activity_bridge.py``, но 0 call-sites в
``src/backend/``). Тест фиксирует composition-layer wiring и
гарантирует, что production lifespan вызывает
``register_langgraph_checkpoint_activities`` → ``bridge.decorate()``
→ передаёт activities в ``start_temporal_worker_runtime``.

Подход: тесты разнесены на 3 уровня (как требует cycle-7 brief):
    1. ``_build_temporal_activities`` собирает checkpoint activities.
    2. Wrapper в ``starting_operations`` форвардит activities в Worker.
    3. ``start_temporal_worker_runtime`` принимает kw-only ``activities``
       и пробрасывает его в ``Worker(...)``.

Runtime: все ``temporalio.*`` импорты мокаются через ``sys.modules`` —
SDK может отсутствовать в test env (lazy-import pattern).
"""

# ruff: noqa: S101

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.core.workflow_registry import workflow_registry
from src.backend.dsl.workflow.compiler.activity_bridge import (
    LANGGRAPH_CHECKPOINT_GET_ACTIVITY,
    LANGGRAPH_CHECKPOINT_PUT_ACTIVITY,
    _langgraph_checkpoint_get_activity,
    _langgraph_checkpoint_put_activity,
)


@pytest.fixture(autouse=True)
def _reset_state() -> None:
    """Сбрасывает singleton runtime + registry между тестами."""
    from src.backend.infrastructure.workflow import temporal_worker_runtime as mod

    mod.reset_temporal_worker_runtime()
    workflow_registry.clear()
    yield
    mod.reset_temporal_worker_runtime()
    workflow_registry.clear()


def _patch_temporalio_activity() -> MagicMock:
    """Подменяет ``temporalio.activity`` чтобы ``bridge.decorate()`` работал."""

    def _fake_defn(name: str = ""):  # type: ignore[no-untyped-def]
        def _decorator(fn):  # type: ignore[no-untyped-def]
            wrapped = MagicMock(wraps=fn)
            wrapped.__temporal_activity_definition = SimpleNamespace(name=name)
            wrapped.__name__ = getattr(fn, "__name__", name)
            return wrapped

        return _decorator

    fake_activity = MagicMock()
    fake_activity.defn = MagicMock(side_effect=_fake_defn)
    return fake_activity


# --- (1) composition-layer builder ------------------------------------------


class TestBuildTemporalActivities:
    """D-AUDIT-704 fix: ``_build_temporal_activities`` строит activity list."""

    @pytest.mark.asyncio
    async def test_returns_two_checkpoint_activities(self) -> None:
        """Bridge с LangGraph checkpoint registration → 2 activities в cache."""
        from src.backend.plugins.composition.setup_infra import lifecycle

        fake_activity = _patch_temporalio_activity()
        with patch.dict(
            "sys.modules",
            {"temporalio": MagicMock(activity=fake_activity)},
        ):
            activities = await lifecycle._build_temporal_activities()

        assert len(activities) == 2
        # Identity-match (как в test_langgraph_checkpoint.py):
        # cache entry == module-level function reference.
        names = {getattr(fn, "__name__", None) for fn in activities}
        # decorated MagicMock wraps fn → __name__ от inner fn
        assert any(n is not None for n in names)

    @pytest.mark.asyncio
    async def test_registers_langgraph_checkpoint_activities(self) -> None:
        """``register_langgraph_checkpoint_activities`` вызывается в build path."""
        from src.backend.plugins.composition.setup_infra import lifecycle

        fake_register = MagicMock()
        fake_bridge = MagicMock()
        fake_bridge._cache = {}
        fake_bridge.decorate = MagicMock()

        # Patch модуль activity_bridge (composition делает lazy import).
        with patch(
            "src.backend.dsl.workflow.compiler.activity_bridge.ActivityBridge",
            return_value=fake_bridge,
        ), patch(
            "src.backend.dsl.workflow.compiler.activity_bridge.register_langgraph_checkpoint_activities",
            fake_register,
        ):
            await lifecycle._build_temporal_activities()

        fake_register.assert_called_once_with(fake_bridge)
        fake_bridge.decorate.assert_called_once()

    @pytest.mark.asyncio
    async def test_decorate_failure_returns_empty_list(self) -> None:
        """``bridge.decorate`` raises (temporalio не установлен) → []."""
        from src.backend.plugins.composition.setup_infra import lifecycle

        fake_bridge = MagicMock()
        fake_bridge._cache = {LANGGRAPH_CHECKPOINT_GET_ACTIVITY: MagicMock()}
        fake_bridge.decorate = MagicMock(
            side_effect=RuntimeError("temporalio SDK not installed")
        )

        with patch(
            "src.backend.dsl.workflow.compiler.activity_bridge.ActivityBridge",
            return_value=fake_bridge,
        ):
            activities = await lifecycle._build_temporal_activities()

        assert activities == []

    @pytest.mark.asyncio
    async def test_activity_bridge_import_failure_returns_empty_list(self) -> None:
        """``activity_bridge`` import failure → [] (graceful degradation)."""
        from src.backend.plugins.composition.setup_infra import lifecycle

        # Hide the import → ImportError
        with patch.dict("sys.modules", {"temporalio": MagicMock()}):
            with patch(
                "src.backend.plugins.composition.setup_infra.lifecycle.app_logger"
            ):
                # Force ImportError by patching builtins.__import__
                import builtins

                real_import = builtins.__import__

                def _import(name, *args, **kwargs):  # type: ignore[no-untyped-def]
                    if name.endswith("activity_bridge"):
                        raise ImportError("simulated: activity_bridge hidden")
                    return real_import(name, *args, **kwargs)

                with patch("builtins.__import__", side_effect=_import):
                    activities = await lifecycle._build_temporal_activities()

        assert activities == []


# --- (2) wrapper в starting_operations --------------------------------------


class TestWrapperInStartingOperations:
    """D-AUDIT-704 fix: wrapper в ``starting_operations`` форвардит activities."""

    def test_starting_operations_uses_wrapper(self) -> None:
        """``start_temporal_worker_runtime`` entry — это wrapper, не bare func."""
        from src.backend.plugins.composition.setup_infra import lifecycle

        entry = next(
            (
                (name, op)
                for name, op, _guard in lifecycle.starting_operations
                if name == "start_temporal_worker_runtime"
            ),
            None,
        )
        assert entry is not None, (
            "start_temporal_worker_runtime entry отсутствует в starting_operations"
        )
        _name, op = entry
        assert op is lifecycle._start_temporal_worker_runtime_with_activities
        # Sanity: wrapper — async функция (вызывается из perform_infrastructure_operation)
        import inspect

        assert inspect.iscoroutinefunction(op)

    @pytest.mark.asyncio
    async def test_wrapper_calls_register_and_passes_activities(self) -> None:
        """Wrapper зовёт ``_build_temporal_activities`` → ``start_temporal_worker_runtime(activities=...)``."""
        from src.backend.plugins.composition.setup_infra import lifecycle
        from src.backend.infrastructure.workflow import temporal_worker_runtime

        fake_activities = [MagicMock(name="act1"), MagicMock(name="act2")]
        # Patch source module (wrapper делает local re-import — patch на
        # ``lifecycle.start_temporal_worker_runtime`` не подхватывается).
        with patch.object(
            lifecycle,
            "_build_temporal_activities",
            new=AsyncMock(return_value=fake_activities),
        ), patch.object(
            temporal_worker_runtime,
            "start_temporal_worker_runtime",
            new=AsyncMock(),
        ) as mock_start:
            await lifecycle._start_temporal_worker_runtime_with_activities()

        mock_start.assert_awaited_once_with(activities=fake_activities)


# --- (3) start_temporal_worker_runtime принимает activities ----------------


class TestStartTemporalWorkerRuntimeActivitiesParam:
    """D-AUDIT-704 fix: kw-only ``activities`` пробрасывается в Worker."""

    @pytest.mark.asyncio
    async def test_activities_propagates_to_worker(self) -> None:
        """``start_temporal_worker_runtime(activities=[...])`` → Worker(...)."""
        from src.backend.infrastructure.workflow import temporal_worker_runtime as mod

        fake_worker_instance = MagicMock(name="Worker-instance")
        fake_worker_instance.shutdown = AsyncMock(return_value=None)
        fake_worker_instance.run = MagicMock(return_value=MagicMock())

        fake_worker_cls = MagicMock(return_value=fake_worker_instance)

        fake_worker_mod = MagicMock()
        fake_worker_mod.Worker = fake_worker_cls

        fake_factory = MagicMock()
        fake_client = MagicMock()
        fake_factory.get_client = AsyncMock(return_value=fake_client)

        fake_flags = MagicMock()
        fake_flags.workflow_use_temporal = True

        sentinel_activities = [MagicMock(name="a1"), MagicMock(name="a2")]

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
            await mod.start_temporal_worker_runtime(activities=sentinel_activities)

        kwargs = fake_worker_mod.Worker.call_args.kwargs
        assert kwargs["activities"] == sentinel_activities

    @pytest.mark.asyncio
    async def test_default_activities_is_empty_list(self) -> None:
        """Backward-compat: без kwarg → activities=[] (cycle 1 поведение)."""
        from src.backend.infrastructure.workflow import temporal_worker_runtime as mod

        fake_worker_instance = MagicMock(name="Worker-instance")
        fake_worker_instance.shutdown = AsyncMock(return_value=None)
        fake_worker_instance.run = MagicMock(return_value=MagicMock())

        fake_worker_cls = MagicMock(return_value=fake_worker_instance)

        fake_worker_mod = MagicMock()
        fake_worker_mod.Worker = fake_worker_cls

        fake_factory = MagicMock()
        fake_factory.get_client = AsyncMock(return_value=MagicMock())

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

        kwargs = fake_worker_mod.Worker.call_args.kwargs
        assert kwargs["activities"] == []


# --- (4) end-to-end: checkpoint identity match ------------------------------


def test_checkpoint_activities_identity_in_bridge() -> None:
    """Identity guard: register_langgraph_checkpoint_activities сохраняет reference."""
    from src.backend.dsl.workflow.compiler.activity_bridge import (
        ActivityBridge,
        register_langgraph_checkpoint_activities,
    )

    bridge = ActivityBridge()
    register_langgraph_checkpoint_activities(bridge)

    assert (
        bridge._cache[LANGGRAPH_CHECKPOINT_GET_ACTIVITY]
        is _langgraph_checkpoint_get_activity
    )
    assert (
        bridge._cache[LANGGRAPH_CHECKPOINT_PUT_ACTIVITY]
        is _langgraph_checkpoint_put_activity
    )
