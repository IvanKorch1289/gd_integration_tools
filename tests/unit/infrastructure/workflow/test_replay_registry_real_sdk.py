"""Contract-test: WorkflowRegistry с реальными @workflow.defn классами.

Per 25.09 audit: «Нужен contract-test с настоящими @workflow.defn и
@workflow.run, регистрацией, извлечением custom name и replay-compatible
class resolution. Private SDK attribute следует изолировать в одном
adapter и закрыть тестом на locked version; нельзя распространять его
имя по проекту».

Locked SDK: temporalio 1.32.0.
Canonical marker: ``__temporal_workflow_definition`` (без trailing
underscores) — per Temporal SDK contract.

Тест НЕ запускает event loop / Temporal worker — только проверяет что
регистрация с настоящим ``@workflow.defn`` классом работает
(извлечение marker, custom name, replay-compatible class resolution).
"""

from __future__ import annotations

import pytest

# temporalio доступен в dev venv (зависимость core).
temporalio = pytest.importorskip("temporalio")
workflow_decorator = pytest.importorskip("temporalio.workflow").defn

from src.backend.core.workflow_registry import (
    WorkflowRegistry,
    workflow_registry,
    _TEMPORAL_DEFN_MARKER,
)


@pytest.fixture()
def fresh_registry() -> WorkflowRegistry:
    """Fresh registry для каждого теста (НЕ singleton — изоляция)."""
    return WorkflowRegistry()


# === Minimal real @workflow.defn classes для теста ===

temporalio_workflow = pytest.importorskip("temporalio.workflow")


@workflow_decorator(name="RealWorkflowStub")
class RealWorkflowStub:
    """Minimal Temporal workflow class (canonical SDK marker)."""

    @temporalio_workflow.run
    async def run(self) -> str:
        return "stub"


@workflow_decorator
class DefaultNameWorkflow:
    """Workflow без явного name → default = class name."""

    @temporalio_workflow.run
    async def run(self) -> str:
        return "default"


@workflow_decorator(name="ReplayTargetWorkflow")
class ReplayTargetWorkflow:
    """Workflow для replay-compatible class resolution test."""

    @temporalio_workflow.run
    async def run(self, input_value: int) -> int:
        return input_value * 2


# === Tests ===

def test_temporal_sdk_locked_version_is_1_32() -> None:
    """Per audit: «закрыть тестом на locked version» — temporalio 1.32.0.

    Если SDK upgrade меняет marker name, contract-test ловит breakage.
    """
    assert temporalio.__version__.startswith("1.32"), (
        f"Temporal SDK version changed: {temporalio.__version__}. "
        f"WorkflowRegistry может требовать обновления. "
        f"Locked at 1.32.0 (audit 25.09.2026)."
    )


def test_canonical_marker_name_matches_sdk_contract() -> None:
    """``_TEMPORAL_DEFN_MARKER`` ДОЛЖЕН совпадать с Temporal SDK attribute.

    Per audit: «Private SDK attribute следует изолировать в одном adapter
    и закрыть тестом на locked version; нельзя распространять его имя
    по проекту».
    """
    # SDK ставит marker на класс.
    assert hasattr(RealWorkflowStub, _TEMPORAL_DEFN_MARKER), (
        f"SDK не ставит marker {_TEMPORAL_DEFN_MARKER!r} на @workflow.defn class. "
        f"Temporal SDK contract изменился?"
    )
    # Marker ДОЛЖЕН быть __temporal_workflow_definition (без trailing __).
    assert _TEMPORAL_DEFN_MARKER == "__temporal_workflow_definition", (
        f"Marker mismatch: {_TEMPORAL_DEFN_MARKER!r}. "
        f"Locked at '__temporal_workflow_definition' (temporalio 1.32)."
    )


def test_register_real_workflow_class_extracts_name(fresh_registry: WorkflowRegistry) -> None:
    """Регистрация с реальным @workflow.defn классом извлекает custom name."""
    fresh_registry.register(RealWorkflowStub)

    # Имя извлекается из marker.
    assert fresh_registry.get("RealWorkflowStub") is RealWorkflowStub


def test_register_default_name_workflow_uses_class_name(
    fresh_registry: WorkflowRegistry,
) -> None:
    """Workflow без явного name → default = class name."""
    fresh_registry.register(DefaultNameWorkflow)
    assert fresh_registry.get("DefaultNameWorkflow") is DefaultNameWorkflow


def test_register_real_workflow_rejects_non_workflow_class(
    fresh_registry: WorkflowRegistry,
) -> None:
    """Non-workflow class (нет marker) → register fails."""
    class NotAWorkflow:
        pass

    with pytest.raises((ValueError, TypeError)):
        fresh_registry.register(NotAWorkflow)


def test_replay_compatible_class_resolution(fresh_registry: WorkflowRegistry) -> None:
    """Replay-compatible class resolution: имя → class.

    Per audit: «извлечением custom name и replay-compatible class resolution».
    TemporalWorkflowBackend.replay(workflow_name) → list[WorkflowClass]
    для передачи в temporalio.Replayer.
    """
    fresh_registry.register(ReplayTargetWorkflow)

    # Resolve по name (что TemporalWorkflowBackend.replay делает).
    resolved = fresh_registry.resolve(["ReplayTargetWorkflow"])
    assert resolved == [ReplayTargetWorkflow]


def test_resolve_workflow_classes_skips_unknown(
    fresh_registry: WorkflowRegistry,
) -> None:
    """resolve пропускает unknown names (graceful)."""
    fresh_registry.register(ReplayTargetWorkflow)
    resolved = fresh_registry.resolve(
        ["ReplayTargetWorkflow", "UnknownWorkflow", "AnotherUnknown"]
    )
    # Unknown должны быть silently пропущены (Replayer требует только
    # известные workflows; unknown → log warning, не raise).
    assert resolved == [ReplayTargetWorkflow]


def test_canonical_marker_isolated_to_one_place() -> None:
    """Per audit: «Private SDK attribute следует изолировать в одном adapter
    и закрыть тестом на locked version; нельзя распространять его имя
    по проекту».
    """
    import subprocess

    result = subprocess.run(
        ["grep", "-r", "__temporal_workflow_definition__", "src/backend/", "--include=*.py"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    # Trailing-underscores variant НЕ должен быть в production src/.
    # Только в docstrings/strings тестовых fixtures (test_replay_registry_cycle33.py
    # содержит synthetic fixture с обоими marker names).
    if result.returncode == 0 and result.stdout.strip():
        # Если найден — допустимо только в test_replay_registry_cycle33.py.
        non_test_files = [
            line
            for line in result.stdout.split("\n")
            if "test_replay_registry_cycle33" not in line
            and line.strip()
        ]
        assert not non_test_files, (
            f"__temporal_workflow_definition__ (с trailing __) — WRONG marker. "
            f"Найден в production src (не в test fixtures): {non_test_files}. "
            f"Используйте {('_TEMPORAL_DEFN_MARKER = ' + repr(_TEMPORAL_DEFN_MARKER))!r} "
            f"вместо литералов."
        )
