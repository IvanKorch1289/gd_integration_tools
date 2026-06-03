"""Unit tests for src.backend.core.config.features.workflow (T1.3.6 split)."""

from __future__ import annotations

import os

from src.backend.core.config.features import feature_flags
from src.backend.core.config.features.workflow import WorkflowFlags


class TestWorkflowFlagsClass:
    def test_workflow_flags_importable(self) -> None:
        assert WorkflowFlags is not None

    def test_workflow_flags_instantiates(self) -> None:
        flags = WorkflowFlags()
        assert flags.workflow_legacy_disabled is False
        assert flags.workflow_yaml_round_trip is False
        assert flags.workflow_bpmn_import is False
        assert flags.workflow_gateways_enabled is False

    def test_workflow_env_vars(self) -> None:
        os.environ["FEATURE_WORKFLOW_YAML_ROUND_TRIP"] = "true"
        os.environ["FEATURE_WORKFLOW_GATEWAYS_ENABLED"] = "true"
        try:
            flags = WorkflowFlags()
            assert flags.workflow_yaml_round_trip is True
            assert flags.workflow_gateways_enabled is True
            # Other 2 still default
            assert flags.workflow_legacy_disabled is False
            assert flags.workflow_bpmn_import is False
        finally:
            del os.environ["FEATURE_WORKFLOW_YAML_ROUND_TRIP"]
            del os.environ["FEATURE_WORKFLOW_GATEWAYS_ENABLED"]

    def test_workflow_field_count(self) -> None:
        fields = WorkflowFlags.model_fields
        names = list(fields.keys())
        assert "workflow_legacy_disabled" in names
        assert "workflow_yaml_round_trip" in names
        assert "workflow_bpmn_import" in names
        assert "workflow_gateways_enabled" in names
        assert len(names) == 4


class TestWorkflowFlagsComposition:
    def test_feature_flags_inherits_workflow_fields(self) -> None:
        assert hasattr(feature_flags, "workflow_legacy_disabled")
        assert hasattr(feature_flags, "workflow_yaml_round_trip")
        assert hasattr(feature_flags, "workflow_bpmn_import")
        assert hasattr(feature_flags, "workflow_gateways_enabled")
        assert feature_flags.workflow_gateways_enabled is False

    def test_feature_flags_class_mro(self) -> None:
        from src.backend.core.config.features import FeatureFlags
        mro_names = [c.__name__ for c in FeatureFlags.__mro__]
        # Все 5 mixins в MRO
        assert "AuthFlags" in mro_names
        assert "SecurityFlags" in mro_names
        assert "ObservabilityFlags" in mro_names
        assert "NetFlags" in mro_names
        assert "WorkflowFlags" in mro_names
