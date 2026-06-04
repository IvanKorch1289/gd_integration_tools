"""Tests for the S39 W4 integration.py split skeleton (audit-only).

These tests verify ONLY the skeleton structure of the proposed mixin split
created by the classification subagent. They do NOT exercise the actual
method bodies (which will be moved by the orchestrator in a follow-up).

The test covers four invariants:
  1. Each skeleton class can be imported and has ``__slots__ = ()``.
  2. The class docstring mentions the expected number of planned methods.

Test layout note: the task description specified
``tests/unit/core/test_integration_split_audit.py`` but the actual file
under classification is in ``src/backend/dsl/builders/integration_core.py``,
so the test lives in the corresponding ``tests/unit/dsl/builders/`` folder.
"""

# ruff: noqa: S101

from __future__ import annotations

import re

import pytest


def _count_method_lines(docstring: str) -> int:
    """Count bullet lines (lines starting with two-space indent + 'N.') in a docstring."""
    return len(re.findall(r"^\s+\d+\.\s+\w+", docstring, flags=re.MULTILINE))


class TestIntegrationGroupASkeleton:
    """Verify the runtime-invocation skeleton (Group A)."""

    def test_import(self) -> None:
        from src.backend.dsl.builders.integration_group_a import IntegrationGroupA

        assert IntegrationGroupA is not None

    def test_slots_is_empty_tuple(self) -> None:
        from src.backend.dsl.builders.integration_group_a import IntegrationGroupA

        assert IntegrationGroupA.__slots__ == ()

    def test_docstring_lists_six_methods(self) -> None:
        from src.backend.dsl.builders.integration_group_a import IntegrationGroupA

        doc = IntegrationGroupA.__doc__ or ""
        count = _count_method_lines(doc)
        assert count == 6, (
            f"Expected Group A docstring to list 6 methods, found {count}. "
            f"Docstring: {doc!r}"
        )

    def test_docstring_mentions_runtime_concept(self) -> None:
        from src.backend.dsl.builders.integration_group_a import IntegrationGroupA

        doc = (IntegrationGroupA.__doc__ or "").lower()
        # The class is about runtime delegation / invocation
        assert "invocation" in doc or "runtime" in doc or "deleg" in doc


class TestIntegrationGroupBSkeleton:
    """Verify the data/AI/ML/documents/utility skeleton (Group B)."""

    def test_import(self) -> None:
        from src.backend.dsl.builders.integration_group_b import IntegrationGroupB

        assert IntegrationGroupB is not None

    def test_slots_is_empty_tuple(self) -> None:
        from src.backend.dsl.builders.integration_group_b import IntegrationGroupB

        assert IntegrationGroupB.__slots__ == ()

    def test_docstring_lists_nine_methods(self) -> None:
        from src.backend.dsl.builders.integration_group_b import IntegrationGroupB

        doc = IntegrationGroupB.__doc__ or ""
        count = _count_method_lines(doc)
        assert count == 9, (
            f"Expected Group B docstring to list 9 methods, found {count}. "
            f"Docstring: {doc!r}"
        )

    def test_docstring_mentions_data_or_ai_concept(self) -> None:
        from src.backend.dsl.builders.integration_group_b import IntegrationGroupB

        doc = (IntegrationGroupB.__doc__ or "").lower()
        # The class is about data processing, AI, ML, documents
        keywords = ("data", "ai", "ml", "doc")
        assert any(kw in doc for kw in keywords), (
            f"Expected Group B docstring to mention at least one of {keywords}"
        )


class TestSkeletonRoundTrip:
    """Make sure the two skeletons can be imported together and don't conflict."""

    def test_both_imports_succeed(self) -> None:
        from src.backend.dsl.builders.integration_group_a import IntegrationGroupA
        from src.backend.dsl.builders.integration_group_b import IntegrationGroupB

        assert IntegrationGroupA is not IntegrationGroupB
        assert IntegrationGroupA.__name__ == "IntegrationGroupA"
        assert IntegrationGroupB.__name__ == "IntegrationGroupB"

    def test_total_method_count_matches_source(self) -> None:
        """15 methods in the source IntegrationCoreMixin → 6 + 9 across the two skeletons."""
        from src.backend.dsl.builders.integration_group_a import IntegrationGroupA
        from src.backend.dsl.builders.integration_group_b import IntegrationGroupB

        total = _count_method_lines(
            IntegrationGroupA.__doc__ or ""
        ) + _count_method_lines(IntegrationGroupB.__doc__ or "")
        assert total == 15, f"Expected 15 methods total across both groups, got {total}"


@pytest.mark.parametrize(
    "method_name",
    [
        "dispatch_action",
        "invoke",
        "to_route",
        "invoke_workflow",
        "cancel_workflow",
        "call_function",
    ],
)
def test_group_a_docstring_mentions_method(method_name: str) -> None:
    from src.backend.dsl.builders.integration_group_a import IntegrationGroupA

    doc = IntegrationGroupA.__doc__ or ""
    assert method_name in doc, f"Group A docstring missing method: {method_name}"


@pytest.mark.parametrize(
    "method_name",
    [
        "audit",
        "scan_file",
        "get_setting",
        "validate_response",
        "render_docx",
        "render_xlsx",
        "evaluate_rules",
        "llm_structured",
        "ml_predict",
    ],
)
def test_group_b_docstring_mentions_method(method_name: str) -> None:
    from src.backend.dsl.builders.integration_group_b import IntegrationGroupB

    doc = IntegrationGroupB.__doc__ or ""
    assert method_name in doc, f"Group B docstring missing method: {method_name}"
