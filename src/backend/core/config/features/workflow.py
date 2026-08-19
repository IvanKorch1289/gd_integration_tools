"""Workflow feature-flags (T1.3.6 split from core.config.features.__init__).

Извлечено 4 K4 — Workflow flags (S38 P1.1 epic, T1.3.6 PR):
- workflow_legacy_disabled
- workflow_yaml_round_trip
- workflow_bpmn_import
- workflow_gateways_enabled
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkflowFlags(BaseSettings):
    """K4 — Workflow (K3 K4). Owner: K4 Workflow, K3 Workflow DSL.

    Per S38 T1.3.6, извлечено из monolithic ``core.config.features.FeatureFlags``
    для eventual multi-inheritance split (9 доменов, 10 PRs).

    Re-export в ``__init__.py``:
        from src.backend.core.config.features.workflow import WorkflowFlags
        class FeatureFlags(..., WorkflowFlags, ...):
            ...

    Env-var prefix: ``FEATURE_`` (inherited from parent pydantic-settings config).

    # cycle-3/D-AUDIT-07: defaults aligned with description "default-OFF"
    # (workflow_legacy_disabled, workflow_yaml_round_trip, workflow_bpmn_import,
    # workflow_gateways_enabled — все default=False, не default=True).
    """

    model_config = SettingsConfigDict(env_prefix="FEATURE_", extra="forbid")

    workflow_legacy_disabled: bool = Field(
        default=False,  # D-AUDIT-11 fix (cycle 1): aligned with docstring "default-OFF"
        title="Workflow: отключить legacy infrastructure/workflow/state*",
        description=(
            "K4 Wave 1. Owner: K4 Workflow. ETA: S2-W1. "
            "При True блокирует все импорты из legacy 4 файлов "
            "(state.py/state_store.py/event_store.py/state_projector.py). "
            "default-OFF до миграции 19 импортёров на TemporalFacade."
        ),
    )

    workflow_yaml_round_trip: bool = Field(
        default=False,  # D-AUDIT-11 fix (cycle 1): aligned with docstring "default-OFF"
        title="Workflow: YAML round-trip API (to_yaml/from_yaml/diff)",
        description=(
            "K4 Wave 2. Owner: K4 Workflow. ETA: S2-W2. "
            "Активирует to_yaml()/from_yaml()/diff() API на WorkflowBuilder. "
            "default-OFF до golden-snapshot тестов на 5 эталонных workflow."
        ),
    )

    workflow_bpmn_import: bool = Field(
        default=False,  # D-AUDIT-11 fix (cycle 1): aligned with docstring "default-OFF"
        title="Workflow: BPMN 2.0 import через SpiffWorkflow 3.0",
        description=(
            "K4 Wave 3. Owner: K4 Workflow. ETA: S2-W3. "
            "Активирует SpiffWorkflow 3.0 → WorkflowSpec → Temporal compiler. "
            "default-OFF до research-spike ADR + sample-теста."
        ),
    )

    workflow_gateways_enabled: bool = Field(
        default=False,  # D-AUDIT-11 fix (cycle 1): aligned with docstring "default-OFF"
        title="Workflow: XOR/AND/OR gateways (.gateway_xor/.gateway_and/.gateway_or)",
        description=(
            "K3 Wave 4. Owner: K3 Workflow DSL. ETA: S3-W4. "
            "Активирует gateway-примитивы BPMN-стиля в WorkflowBuilder: "
            "XOR (exclusive branching), AND (parallel wait_all), OR (inclusive wait_any). "
            "GatewaySpec + BranchSpec → GatewayCompiler → Temporal-IR dict. "
            "default-OFF до интеграции GatewayCompiler с emitter.py и staging-smoke."
        ),
    )

    workflow_orchestrator_enabled: bool = Field(
        default=False,
        title="Workflow: OrchestratorEngine (агентная маршрутизация между LLM-агентами)",
        description=(
            "S28 W4: OrchestratorEngine.route(task) с JMESPath routing rules. "
            "При True — evaluates routing rules и выбирает agent; "
            "при False — fallback на default_agent (или ошибка, если не указан). "
            "default-OFF до интеграции с AgentRegistry и production-smoke."
        ),
    )

    # Sprint 8 P1-1: WorkflowSubprocess standalone guard flag.
    # default=True (fail-closed) — в production subworkflow без parent workflow
    # отвергается (избегаем orphan workflows). dev/test могут переключить в False
    # через FEATURE_WORKFLOW_SUBPROCESS_REQUIRE_PARENT=false.
    # Без explicit поля код в workflow_subprocess.py:127-131 fallback на True
    # через except — silent default. Этот флаг делает default observable.
    workflow_subprocess_require_parent: bool = Field(
        default=True,
        title="Workflow: WorkflowSubprocess требует parent_workflow_handle",
        description=(
            "Sprint 8 P1-1: при True WorkflowSubprocessProcessor refuses to start "
            "child workflow если parent_workflow_handle is None (избегаем orphan "
            "workflows без Cancel/ContinueAsNew propagation). "
            "default=True (fail-closed) — production-safe; dev/test могут "
            "переключить в False через FEATURE_WORKFLOW_SUBPROCESS_REQUIRE_PARENT=false."
        ),
    )


__all__ = ("WorkflowFlags",)
