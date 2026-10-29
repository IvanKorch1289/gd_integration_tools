"""ADR-0395 — Temporal Worker получает все activity-функции деклараций.

Дефект (3, high): ``setup_infra.lifecycle._build_temporal_activities``
регистрировал только 2 activity (LangGraph checkpoint) — ``bridge._cache``
без ``collect_activities``. Любой ``workflow.execute_activity`` из
YAML-декларации падал с ``ActivityNotRegisteredError``. Дополнительно
worker не поднимался в lifespan (feature-flag ``workflow_use_temporal``
default-OFF) без понятного предупреждения.

Проверяем:
* activity-list включает activity каждого шага декларации;
* workflow-классы деклараций скомпилированы (worker их видит);
* при выключенном флаге — понятное предупреждение, а не молчание.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.backend.dsl.workflow.spec import WorkflowDeclaration

_REPO_ROOT = Path(__file__).resolve().parents[4]


def _declaration_with_activity(name: str) -> WorkflowDeclaration:
    """Декларация с одним activity-шагом."""
    return WorkflowDeclaration.model_validate(
        {"name": name, "steps": [{"type": "activity", "name": "orders.create"}]}
    )


class TestTemporalActivityCollection:
    """Сбор activity-функций для Worker'а."""

    @pytest.mark.asyncio
    async def test_collects_activity_of_every_declaration_step(self) -> None:
        """Activity-list содержит activity каждого шага (не только checkpoint)."""
        from src.backend.dsl.workflow.compiler.activity_bridge import ActivityBridge
        from src.backend.plugins.composition.setup_infra.lifecycle import (
            _build_temporal_activities,
        )

        decl = _declaration_with_activity("worker.collect.test")
        bridge = ActivityBridge()
        names = [
            fn.__activity_name__
            for fn in bridge.collect_activities([decl])  # type: ignore[attr-defined]
        ]

        # Шаблон из lifecycle собирает activities из скомпилированных деклараций;
        # проверяем, что в bridge попадают activity шагов, а не только checkpoint.
        assert "orders.create" in names
        # Sanity: функция lifecycle доступна и возвращает список.
        activities = await _build_temporal_activities()
        assert isinstance(activities, list)

    @pytest.mark.asyncio
    async def test_worker_registration_uses_collect_activities(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Worker получает activity из скомпилированных деклараций."""
        from src.backend.dsl.workflow.compiler import activity_bridge as bridge_module
        from src.backend.plugins.composition import workflow_setup
        from src.backend.plugins.composition.setup_infra import lifecycle

        decl = _declaration_with_activity("worker.registration.test")
        monkeypatch.setattr(
            workflow_setup, "ensure_workflow_declarations_loaded", lambda **_: [decl]
        )
        collected: list[str] = []

        original = bridge_module.ActivityBridge.collect_activities

        def _spy(self: Any, declarations: Any, **kwargs: Any) -> Any:
            for item in declarations:
                for step in item.steps:
                    collected.append(step.name)
            return original(self, declarations, **kwargs)

        monkeypatch.setattr(
            bridge_module.ActivityBridge, "collect_activities", _spy, raising=True
        )

        activities = await lifecycle._build_temporal_activities()

        assert "orders.create" in collected
        activity_names = [
            fn.__activity_name__
            for fn in activities  # type: ignore[attr-defined]
        ]
        assert "orders.create" in activity_names
        # Плюс checkpoint activities — они регистрируются всегда.
        assert "_langgraph_checkpoint_get" in activity_names

    @pytest.mark.asyncio
    async def test_declarations_are_compiled_for_worker(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """YAML-декларации компилируются — worker получает workflow-классы."""
        from src.backend.dsl.workflow.compiler.emitter import workflow_registry
        from src.backend.plugins.composition import workflow_setup

        decl = _declaration_with_activity("worker.compiled.test")
        workflow_setup.workflow_compiler_registry.get_or_compile(decl)

        try:
            assert "worker.compiled.test" in workflow_registry
            assert workflow_registry.get("worker.compiled.test") is not None
        finally:
            workflow_registry.unregister("worker.compiled.test")
            workflow_setup.workflow_compiler_registry.unregister("worker.compiled.test")


class TestTemporalWorkerFlag:
    """Feature-flag ``workflow_use_temporal`` (default-OFF)."""

    def test_flag_helper_reflects_feature_flags(self) -> None:
        """``temporal_worker_enabled`` читает актуальное значение флага."""
        from src.backend.infrastructure.workflow.temporal_worker_runtime import (
            temporal_worker_enabled,
        )

        assert isinstance(temporal_worker_enabled(), bool)

    @pytest.mark.asyncio
    async def test_disabled_worker_logs_warning(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Выключенный флаг → WARNING с описанием последствий."""
        from src.backend.infrastructure.workflow import temporal_worker_runtime

        monkeypatch.setattr(
            temporal_worker_runtime, "temporal_worker_enabled", lambda: False
        )
        with caplog.at_level("WARNING"):
            await temporal_worker_runtime.start_temporal_worker_runtime(activities=[])

        messages = " ".join(record.getMessage() for record in caplog.records)
        assert "temporal.worker_runtime.skipped" in messages
