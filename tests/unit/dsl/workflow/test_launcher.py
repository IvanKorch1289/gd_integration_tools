"""Tests for WorkflowLauncher (S19 K3 W1: SemVer range resolution)."""

import pytest

from src.backend.dsl.workflow.launcher import (
    ResolvedWorkflow,
    WorkflowLauncher,
    WorkflowResolutionError,
)


class TestWorkflowLauncher:
    """K3 S19 W1: WorkflowLauncher SemVer range resolution tests."""

    def test_resolve_no_spec_returns_installed_version(self) -> None:
        """When no spec is provided, returns installed version."""
        launcher = WorkflowLauncher(installed_workflows={"wf_a": "1.5.0"})
        result = launcher.resolve("wf_a")
        assert result.version == "1.5.0"
        assert result.spec == "*"

    def test_resolve_with_matching_spec(self) -> None:
        """When spec matches installed version, returns that version."""
        launcher = WorkflowLauncher(installed_workflows={"wf_a": "1.5.0"})
        result = launcher.resolve("wf_a", ">=1.0,<2.0")
        assert result.version == "1.5.0"
        assert result.name == "wf_a"
        assert result.spec == ">=1.0,<2.0"

    def test_resolve_exact_version(self) -> None:
        """Exact version spec works correctly."""
        launcher = WorkflowLauncher(installed_workflows={"wf_a": "2.0.0"})
        result = launcher.resolve("wf_a", ">=2.0.0,<3.0.0")
        assert result.version == "2.0.0"

    def test_resolve_non_matching_spec_fails(self) -> None:
        """When spec doesn't match installed version, raises error."""
        launcher = WorkflowLauncher(installed_workflows={"wf_a": "1.5.0"})
        with pytest.raises(WorkflowResolutionError) as exc_info:
            launcher.resolve("wf_a", ">=2.0.0,<3.0.0")
        assert "does not match spec" in str(exc_info.value)

    def test_resolve_unknown_workflow_fails(self) -> None:
        """When workflow is not installed, raises error."""
        launcher = WorkflowLauncher(installed_workflows={})
        with pytest.raises(WorkflowResolutionError) as exc_info:
            launcher.resolve("unknown_wf")
        assert "not found" in str(exc_info.value)

    def test_resolve_invalid_spec_fails(self) -> None:
        """Invalid SemVer spec raises error."""
        launcher = WorkflowLauncher(installed_workflows={"wf_a": "1.5.0"})
        with pytest.raises(WorkflowResolutionError) as exc_info:
            launcher.resolve("wf_a", "not-a-valid-spec")
        assert "Invalid SemVer spec" in str(exc_info.value)

    def test_is_compatible_true(self) -> None:
        """is_compatible returns True when version matches."""
        launcher = WorkflowLauncher(installed_workflows={"wf_a": "1.5.0"})
        assert launcher.is_compatible("wf_a", ">=1.0,<2.0") is True

    def test_is_compatible_false(self) -> None:
        """is_compatible returns False when version doesn't match."""
        launcher = WorkflowLauncher(installed_workflows={"wf_a": "1.5.0"})
        assert launcher.is_compatible("wf_a", ">=2.0.0,<3.0.0") is False

    def test_get_installed_version(self) -> None:
        """get_installed_version returns correct version."""
        launcher = WorkflowLauncher(installed_workflows={"wf_a": "1.5.0"})
        assert launcher.get_installed_version("wf_a") == "1.5.0"
        assert launcher.get_installed_version("unknown") is None

    def test_set_installed_version(self) -> None:
        """set_installed_version updates the workflow version."""
        launcher = WorkflowLauncher()
        launcher.set_installed_version("wf_a", "2.0.0")
        assert launcher.get_installed_version("wf_a") == "2.0.0"

    def test_list_workflows(self) -> None:
        """list_workflows returns all installed workflow names."""
        launcher = WorkflowLauncher(
            installed_workflows={"wf_a": "1.0.0", "wf_b": "2.0.0"}
        )
        workflows = launcher.list_workflows()
        assert sorted(workflows) == ["wf_a", "wf_b"]

    def test_resolve_best_match_with_multiple_versions(self) -> None:
        """resolve_best_match selects highest matching version."""
        launcher = WorkflowLauncher()
        result = launcher.resolve_best_match(
            "wf_a",
            ">=1.0,<3.0",
            available_versions=["1.0.0", "1.5.0", "2.5.0", "3.0.0"],
        )
        assert result.version == "2.5.0"  # Highest that matches >=1.0,<3.0

    def test_resolve_best_match_no_match_fails(self) -> None:
        """resolve_best_match fails when no version matches."""
        launcher = WorkflowLauncher()
        with pytest.raises(WorkflowResolutionError) as exc_info:
            launcher.resolve_best_match(
                "wf_a", ">=5.0.0,<6.0.0", available_versions=["1.0.0", "2.0.0"]
            )
        assert "No version of workflow" in str(exc_info.value)


class TestResolvedWorkflow:
    """Tests for ResolvedWorkflow dataclass."""

    def test_resolved_workflow_fields(self) -> None:
        """ResolvedWorkflow contains correct fields."""
        resolved = ResolvedWorkflow(name="wf_a", version="1.5.0", spec=">=1.0,<2.0")
        assert resolved.name == "wf_a"
        assert resolved.version == "1.5.0"
        assert resolved.spec == ">=1.0,<2.0"

    def test_resolved_workflow_immutable(self) -> None:
        """ResolvedWorkflow is frozen (immutable)."""
        resolved = ResolvedWorkflow(name="wf_a", version="1.5.0", spec=">=1.0,<2.0")
        with pytest.raises(AttributeError):
            resolved.version = "2.0.0"
