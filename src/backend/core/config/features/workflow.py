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
    """

    model_config = SettingsConfigDict(env_prefix="FEATURE_", extra="forbid")

    workflow_legacy_disabled: bool = Field(
        default=True,
        title="Workflow: отключить legacy infrastructure/workflow/state*",
        description=(
            "K4 Wave 1. Owner: K4 Workflow. ETA: S2-W1. "
            "При True блокирует все импорты из legacy 4 файлов "
            "(state.py/state_store.py/event_store.py/state_projector.py). "
            "default-OFF до миграции 19 импортёров на TemporalFacade."
        ),
    )

    workflow_yaml_round_trip: bool = Field(
        default=True,
        title="Workflow: YAML round-trip API (to_yaml/from_yaml/diff)",
        description=(
            "K4 Wave 2. Owner: K4 Workflow. ETA: S2-W2. "
            "Активирует to_yaml()/from_yaml()/diff() API на WorkflowBuilder. "
            "default-OFF до golden-snapshot тестов на 5 эталонных workflow."
        ),
    )

    workflow_bpmn_import: bool = Field(
        default=True,
        title="Workflow: BPMN 2.0 import через SpiffWorkflow 3.0",
        description=(
            "K4 Wave 3. Owner: K4 Workflow. ETA: S2-W3. "
            "Активирует SpiffWorkflow 3.0 → WorkflowSpec → Temporal compiler. "
            "default-OFF до research-spike ADR + sample-теста."
        ),
    )

    workflow_gateways_enabled: bool = Field(
        default=True,
        title="Workflow: XOR/AND/OR gateways (.gateway_xor/.gateway_and/.gateway_or)",
        description=(
            "K3 Wave 4. Owner: K3 Workflow DSL. ETA: S3-W4. "
            "Активирует gateway-примитивы BPMN-стиля в WorkflowBuilder: "
            "XOR (exclusive branching), AND (parallel wait_all), OR (inclusive wait_any). "
            "GatewaySpec + BranchSpec → GatewayCompiler → Temporal-IR dict. "
            "default-OFF до интеграции GatewayCompiler с emitter.py и staging-smoke."
        ),
    )


__all__ = ("WorkflowFlags",)
