# ruff: noqa: S101
"""Тесты workflow versioning (Sprint 7 K3 ``[wave:s7/k3-workflow-versioning]``)."""

from __future__ import annotations

import pytest

from src.backend.dsl.workflow.versioning import (
    WorkflowVersion,
    WorkflowVersionRegistry,
    get_global_registry,
    patched,
    workflow_versioned,
)


class TestWorkflowVersion:
    """Тесты dataclass WorkflowVersion + parse + is_compatible_with."""

    def test_parse_full_semver(self) -> None:
        v = WorkflowVersion.parse("credit.assess", "1.2.3")
        assert v.workflow_id == "credit.assess"
        assert v.major == 1
        assert v.minor == 2
        assert v.patch == 3
        assert v.default_version is True
        assert v.semver == "1.2.3"

    def test_parse_invalid_raises(self) -> None:
        with pytest.raises(ValueError, match="semver"):
            WorkflowVersion.parse("wf", "1.2")  # no patch
        with pytest.raises(ValueError, match="semver"):
            WorkflowVersion.parse("wf", "v1.0.0")

    def test_negative_components_rejected(self) -> None:
        with pytest.raises(ValueError, match=">= 0"):
            WorkflowVersion(workflow_id="x", major=-1, minor=0, patch=0)

    def test_compatibility_same_major(self) -> None:
        a = WorkflowVersion("wf", 1, 0, 0)
        b = WorkflowVersion("wf", 1, 5, 9)
        c = WorkflowVersion("wf", 2, 0, 0)
        d = WorkflowVersion("other", 1, 0, 0)
        assert a.is_compatible_with(b)
        assert not a.is_compatible_with(c)
        assert not a.is_compatible_with(d)


class TestWorkflowVersionRegistry:
    """Тесты register / get_default / history."""

    def test_register_and_get_default(self) -> None:
        reg = WorkflowVersionRegistry()
        v1 = WorkflowVersion("wf", 1, 0, 0, default_version=True)
        reg.register(v1)
        assert reg.get_default("wf") == v1

    def test_history_sorted_by_semver(self) -> None:
        reg = WorkflowVersionRegistry()
        reg.register(WorkflowVersion("wf", 1, 2, 0, default_version=False))
        reg.register(WorkflowVersion("wf", 1, 0, 0, default_version=False))
        reg.register(WorkflowVersion("wf", 1, 1, 5, default_version=True))

        history = reg.history("wf")
        assert [v.semver for v in history] == ["1.0.0", "1.1.5", "1.2.0"]

    def test_new_default_demotes_previous_default(self) -> None:
        reg = WorkflowVersionRegistry()
        reg.register(WorkflowVersion("wf", 1, 0, 0, default_version=True))
        reg.register(WorkflowVersion("wf", 1, 1, 0, default_version=True))

        default = reg.get_default("wf")
        assert default is not None
        assert default.semver == "1.1.0"
        # Старый default уже не default.
        defaults = [
            v for v in reg.versions if v.workflow_id == "wf" and v.default_version
        ]
        assert len(defaults) == 1

    def test_strict_mode_rejects_major_conflict(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.backend.core.config.features import feature_flags

        monkeypatch.setattr(feature_flags, "workflow_versioning_strict", True)

        reg = WorkflowVersionRegistry()
        reg.register(WorkflowVersion("wf", 1, 0, 0, default_version=True))
        with pytest.raises(ValueError, match="strict-mode"):
            reg.register(WorkflowVersion("wf", 2, 0, 0, default_version=True))

    def test_all_workflow_ids(self) -> None:
        reg = WorkflowVersionRegistry()
        reg.register(WorkflowVersion("a", 1, 0, 0))
        reg.register(WorkflowVersion("b", 1, 0, 0))
        reg.register(WorkflowVersion("a", 2, 0, 0))
        assert reg.all_workflow_ids() == ["a", "b"]


class TestWorkflowVersionedDecorator:
    """Тесты декоратора @workflow_versioned + global registry."""

    def test_decorator_registers_version(self) -> None:
        @workflow_versioned(version="3.1.4")
        def my_wf_for_decorator_test() -> None:
            """Тестовый workflow."""

        wv = my_wf_for_decorator_test.__workflow_version__  # type: ignore[attr-defined]
        assert wv.semver == "3.1.4"
        assert wv.workflow_id == "my_wf_for_decorator_test"

        registry = get_global_registry()
        history = registry.history("my_wf_for_decorator_test")
        assert any(v.semver == "3.1.4" for v in history)


class TestPatchedSafety:
    """Тесты lazy-обёртки patched(patch_id) — безопасно без temporalio."""

    def test_returns_false_outside_workflow(self) -> None:
        # В unit-окружении мы НЕ внутри Temporal workflow.defn —
        # обёртка должна вернуть False (legacy ветка).
        assert patched("nonexistent-patch") is False
