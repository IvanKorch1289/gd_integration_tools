"""S3: Docstring coverage test for DSL processors.

Per next-sprint plan S3: docstring coverage 70% → 80%.
Tests measure current coverage and document the baseline.
"""

# ruff: noqa: S101

from __future__ import annotations

import ast
import os


class TestDSLProcessorDocstrings:
    """Measure current docstring coverage in dsl/engine/processors/."""

    def test_processor_files_have_module_docstrings(self):
        """Most processor files should have module-level docstring."""
        processors_dir = "src/backend/dsl/engine/processors"
        total = 0
        with_doc = 0
        for root, _, files in os.walk(processors_dir):
            if "__pycache__" in root:
                continue
            for f in files:
                if not f.endswith(".py") or f == "__init__.py":
                    continue
                p = os.path.join(root, f)
                try:
                    tree = ast.parse(open(p).read())
                except SyntaxError:
                    continue
                total += 1
                if ast.get_docstring(tree):
                    with_doc += 1
        # At least 60% of processor files have module docstring
        ratio = with_doc / total if total else 0
        assert ratio >= 0.6, f"Only {with_doc}/{total} ({ratio:.0%}) have module docstrings"


class TestWorkflowProcessorStructure:
    """S2: workflow/ subdir must exist with re-exports."""

    def test_workflow_subdir_exists(self):
        path = "src/backend/dsl/engine/processors/workflow/__init__.py"
        assert os.path.exists(path), "workflow/ subdir missing (S2: directory split)"

    def test_workflow_subdir_reexports(self):
        path = "src/backend/dsl/engine/processors/workflow/__init__.py"
        with open(path) as f:
            content = f.read()
        for cls in ["CancelWorkflowProcessor", "InvokeWorkflowProcessor",
                    "SubWorkflowProcessor"]:
            assert cls in content, f"Missing re-export: {cls}"

    def test_db_subdir_still_exists(self):
        """db/ subdir (S2 step 1, cycle 30) must still exist."""
        path = "src/backend/dsl/engine/processors/db/__init__.py"
        assert os.path.exists(path), "db/ subdir missing (cycle 30)"
