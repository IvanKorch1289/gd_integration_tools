"""Unit tests for src.backend.dsl.builders.integration_group_a/b (K3 W4, S39).

Subagent #3 (W4 integration split) created 2 skeleton mixin files
+ embedded classification in docstrings. Orchestrator created test
+ audit report + verify + commit.
"""

from __future__ import annotations

from src.backend.dsl.builders.integration_group_a import IntegrationGroupA
from src.backend.dsl.builders.integration_group_b import IntegrationGroupB


class TestIntegrationGroupASkeleton:
    def test_import(self) -> None:
        assert IntegrationGroupA is not None

    def test_slots_empty(self) -> None:
        """Stateless mixin — no instance attrs."""
        assert IntegrationGroupA.__slots__ == ()

    def test_docstring_lists_planned_methods(self) -> None:
        """Docstring должен перечислять planned methods (>= 1)."""
        doc = IntegrationGroupA.__doc__ or ""
        # Should mention dispatcher-related keywords
        assert any(
            kw in doc
            for kw in ("dispatch_action", "invoke", "to_route", "invoke_workflow")
        ), f"GroupA docstring missing planned methods: {doc[:200]}"

    def test_no_method_bodies_yet(self) -> None:
        """SKELETON — only class definition, no real methods."""
        # Only dunders + class-level attrs
        real_methods = [
            name
            for name in dir(IntegrationGroupA)
            if not name.startswith("_")
            and callable(getattr(IntegrationGroupA, name, None))
        ]
        assert real_methods == [], f"GroupA has unexpected methods: {real_methods}"


class TestIntegrationGroupBSkeleton:
    def test_import(self) -> None:
        assert IntegrationGroupB is not None

    def test_slots_empty(self) -> None:
        assert IntegrationGroupB.__slots__ == ()

    def test_docstring_lists_planned_methods(self) -> None:
        doc = IntegrationGroupB.__doc__ or ""
        assert any(
            kw in doc
            for kw in ("audit", "scan_file", "validate_response", "render_docx")
        ), f"GroupB docstring missing planned methods: {doc[:200]}"

    def test_no_method_bodies_yet(self) -> None:
        real_methods = [
            name
            for name in dir(IntegrationGroupB)
            if not name.startswith("_")
            and callable(getattr(IntegrationGroupB, name, None))
        ]
        assert real_methods == [], f"GroupB has unexpected methods: {real_methods}"


class TestIntegrationSplitAudit:
    """W4 = classification + skeleton, NOT a full split.

    Per `refactoring-singleton-registry-split` skill: refactor of
    IntegrationCoreMixin requires LSP diagnostics. Orchestrator will
    perform the actual method moves in a follow-up step.
    """

    def test_group_a_is_invocation_themed(self) -> None:
        """Group A = runtime invocation (dispatch/invoke/to_route/workflow)."""
        doc_a = (IntegrationGroupA.__doc__ or "").lower()
        # Should contain invocation theme keywords
        assert any(
            kw in doc_a
            for kw in ("runtime invocation", "dispatch", "workflow", "sub-route")
        )

    def test_group_b_is_data_themed(self) -> None:
        """Group B = data/AI/ML/documents/utility."""
        doc_b = (IntegrationGroupB.__doc__ or "").lower()
        assert any(
            kw in doc_b
            for kw in ("data", "ai", "ml", "documents", "utility")
        )

    def test_groups_have_different_themes(self) -> None:
        """Group A != Group B (orthogonal split)."""
        assert IntegrationGroupA.__doc__ != IntegrationGroupB.__doc__
