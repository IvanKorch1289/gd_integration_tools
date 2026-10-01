"""F-AT1/F-AT2/F-AT3 (re-audit 2026-10-01, HEAD 2037f9d59) — fail-closed Temporal.

До фикса ``start_temporal_worker_runtime`` на всех пяти путях отказа делал
``return`` + ``_logger.warning``. Операция объявлена
``Criticality.REQUIRED``, но REQUIRED-обёртка оказывалась вакуумной: воркер
рапортовал ``STARTED`` без SDK, без кластера и с ``activities=[]``.

Требование цели: «отсутствие required Temporal activities должно останавливать
worker». Эти тесты фиксируют контракт:

    * feature-flag ВЫКЛЮЧЕН  → no-op, без исключения (фича отключена);
    * feature-flag ВКЛЮЧЁН и воркер не поднялся → ``RuntimeError``.

Каждый тест написан так, чтобы падать при возврате кода к ``return``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

#: Точка патча: start_temporal_worker_runtime делает
#: ``from src.backend.core.config.features import FeatureFlags`` внутри тела,
#: поэтому подменять нужно сам класс в его родном модуле.
_FLAG_TARGET = "src.backend.core.config.features.FeatureFlags"


def _flag(value: bool) -> MagicMock:
    """Подмена FeatureFlags с заданным workflow_use_temporal."""
    flags = MagicMock()
    flags.workflow_use_temporal = value
    return flags


def _act() -> list:
    """Собирает одну activity-заглушку (непустой список)."""

    async def _activity() -> str:  # pragma: no cover - только заглушка
        return "ok"

    return [_activity]


class TestFlagOffIsLegitimateNoOp:
    """Выключенный флаг — осознанный no-op, падать не должен."""

    @pytest.mark.asyncio
    async def test_flag_off_returns_without_raising(self) -> None:
        """F-AT2: флаг off → return, исключения нет."""
        from src.backend.infrastructure.workflow import temporal_worker_runtime as mod

        with patch(_FLAG_TARGET, return_value=_flag(False)):
            await mod.start_temporal_worker_runtime(activities=_act())


class TestFailClosedWhenEnabled:
    """Включённый флаг + нерабочий воркер → обязателен RuntimeError."""

    @pytest.mark.asyncio
    async def test_empty_activities_raises(self) -> None:
        """F-AT3: activities=[] обязан валить операцию, а не проходить как STARTED."""
        from src.backend.infrastructure.workflow import temporal_worker_runtime as mod

        with patch(_FLAG_TARGET, return_value=_flag(True)):
            with pytest.raises(RuntimeError, match="activities пуст"):
                await mod.start_temporal_worker_runtime(activities=[])

    @pytest.mark.asyncio
    async def test_none_activities_raises(self) -> None:
        """F-AT3: activities=None — тот же пустой worker, тот же отказ."""
        from src.backend.infrastructure.workflow import temporal_worker_runtime as mod

        with patch(_FLAG_TARGET, return_value=_flag(True)):
            with pytest.raises(RuntimeError, match="activities пуст"):
                await mod.start_temporal_worker_runtime(activities=None)

    @pytest.mark.asyncio
    async def test_client_unavailable_raises(self) -> None:
        """F-AT1: недоступный Temporal-кластер обязан останавливать worker."""
        from src.backend.infrastructure.workflow import temporal_worker_runtime as mod

        factory = MagicMock()
        factory.get_client = AsyncMock(side_effect=ConnectionError("cluster down"))

        with patch(_FLAG_TARGET, return_value=_flag(True)):
            with patch(
                "src.backend.infrastructure.workflow.temporal_client."
                "TemporalClientFactory",
                return_value=factory,
            ):
                with pytest.raises(RuntimeError, match="не удалось подключиться"):
                    await mod.start_temporal_worker_runtime(activities=_act())

    @pytest.mark.asyncio
    async def test_register_worker_failure_raises(self) -> None:
        """F-AT1: упавший register_worker обязан поднимать вверх."""
        from src.backend.infrastructure.workflow import temporal_worker_runtime as mod

        factory = MagicMock()
        factory._cache = {}
        factory.get_client = AsyncMock(return_value=MagicMock())

        pool = MagicMock()
        pool.register_worker = AsyncMock(side_effect=RuntimeError("worker down"))

        with patch(_FLAG_TARGET, return_value=_flag(True)):
            with patch(
                "src.backend.infrastructure.workflow.temporal_client."
                "TemporalClientFactory",
                return_value=factory,
            ):
                with patch(
                    "src.backend.infrastructure.workflow.temporal_client."
                    "TemporalWorkerPool",
                    return_value=pool,
                ):
                    with pytest.raises(RuntimeError, match="register_worker"):
                        await mod.start_temporal_worker_runtime(activities=_act())


class TestRequiredOperationPropagates:
    """Интеграция с LifecycleRunner: RuntimeError обязан валить REQUIRED-фазу."""

    @pytest.mark.asyncio
    async def test_required_operation_raises_lifecycle_error(self) -> None:
        """Пустой activities → LifecycleStartupError, а не тихий STARTED."""
        from src.backend.infrastructure.workflow import temporal_worker_runtime as mod
        from src.backend.plugins.composition.lifecycle.operations import (
            Criticality,
            LifecycleOperation,
            LifecycleRunner,
            LifecycleStartupError,
        )

        async def _start() -> None:
            await mod.start_temporal_worker_runtime(activities=[])

        runner = LifecycleRunner(
            [
                LifecycleOperation(
                    name="start_temporal_worker_runtime",
                    phase="infrastructure",
                    start=_start,
                    criticality=Criticality.REQUIRED,
                )
            ]
        )

        # Контракт REQUIRED-операции: отказ поднимается как
        # LifecycleStartupError, а не возвращается в отчёте как STARTED.
        with patch(_FLAG_TARGET, return_value=_flag(True)):
            with pytest.raises(LifecycleStartupError) as excinfo:
                await runner.start_all()

        assert "start_temporal_worker_runtime" in str(excinfo.value)
        assert "activities пуст" in str(excinfo.value)


class TestBuildActivitiesIsNotSilent:
    """F-AT3/F-AT4: сбор activities не должен «молча» деградировать."""

    @pytest.mark.asyncio
    async def test_bridge_decorate_failure_returns_empty_list(self) -> None:
        """bridge.decorate() бросает RuntimeError (НЕ ImportError) → []."""
        from src.backend.plugins.composition.setup_infra import lifecycle as comp

        bridge = MagicMock()
        bridge.decorate.side_effect = RuntimeError("temporalio missing")
        bridge._cache = {}

        fake_mod = MagicMock()
        fake_mod.ActivityBridge = MagicMock(return_value=bridge)
        fake_mod.register_langgraph_checkpoint_activities = MagicMock()

        with patch.dict(
            "sys.modules",
            {"src.backend.dsl.workflow.compiler.activity_bridge": fake_mod},
        ):
            result = await comp._build_temporal_activities()

        assert result == [], "ожидался пустой список → воркер не поднимется"
        bridge.decorate.assert_called_once()
