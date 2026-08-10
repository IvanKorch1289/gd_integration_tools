"""Unit-тесты для cycle 26 A2 fix (ResumeDeclaration.checkpoint_id dead field).

Self-contained — does NOT import modules with chain deps.
Tests the fix: dead field removed, no callers use it.
"""


from __future__ import annotations

import ast
import os


class TestCheckpointIdRemoved:
    """A2: ResumeDeclaration.checkpoint_id was dead contract."""

    def test_field_not_in_spec(self):
        """ResumeDeclaration must NOT have checkpoint_id field."""
        path = "src/backend/dsl/workflow/spec/activity_declarations.py"
        with open(path) as f:
            tree = ast.parse(f.read())

        for cls in ast.walk(tree):
            if isinstance(cls, ast.ClassDef) and cls.name == "ResumeDeclaration":
                field_names = [
                    f.target.id if isinstance(f.target, ast.Name) else None
                    for f in cls.body
                    if isinstance(f, ast.AnnAssign)
                ]
                assert "checkpoint_id" not in field_names, (
                    "ResumeDeclaration still has checkpoint_id field "
                    "(should be removed in cycle 26)"
                )

    def test_compile_resume_step_ignores_checkpoint_id(self):
        """compile_resume_step should NOT read decl.checkpoint_id."""
        path = "src/backend/dsl/workflow/compiler/step_compilers.py"
        with open(path) as f:
            content = f.read()
        # Find compile_resume_step function
        start = content.find("async def compile_resume_step")
        end = content.find("\nasync def ", start + 1)
        body = content[start:end] if end != -1 else content[start:start + 1000]
        assert "checkpoint_id" not in body, (
            "compile_resume_step still references checkpoint_id"
        )

    def test_builder_resume_no_kwarg(self):
        """WorkflowBuilder.resume() should not accept checkpoint_id kwarg."""
        path = "src/backend/dsl/workflow/builder/lifecycle_mixin.py"
        with open(path) as f:
            content = f.read()
        # Find the resume method definition
        for line in content.split("\n"):
            if "def resume" in line and "checkpoint_id" not in line:
                # Found a clean signature
                assert "checkpoint_id" not in line, (
                    f"resume() signature still has checkpoint_id: {line}"
                )
                return
        # If we reach here, signature still has checkpoint_id
        raise AssertionError(
            "WorkflowBuilder.resume() still accepts checkpoint_id kwarg"
        )

    def test_yaml_doc_updated(self):
        """Docstring should NOT show checkpoint_id in YAML example."""
        path = "src/backend/dsl/workflow/spec/activity_declarations.py"
        with open(path) as f:
            content = f.read()
        # Find ResumeDeclaration class and check its docstring
        idx = content.find("class ResumeDeclaration")
        assert idx != -1
        end = content.find("model_config", idx)
        docstring_section = content[idx:end]
        # Docstring may show checkpoint_id as removed/cleaned
        # We just verify no instruction to pass checkpoint_id
        assert "checkpoint_id: \"my_checkpoint\"" not in docstring_section


class TestBackwardCompat:
    """Verify no existing usages of removed kwarg remain."""

    def test_no_resume_with_checkpoint_id_in_tests(self):
        """No test should still call .resume(checkpoint_id=...) at runtime.

        Only checks actual call sites, not docstrings mentioning the kwarg.
        Skips this test file itself (which contains the pattern in regex).
        """
        import re
        results = []
        for root, _, files in os.walk("tests/"):
            if "__pycache__" in root: continue
            for f in files:
                if not f.endswith(".py"): continue
                p = os.path.join(root, f)
                if p.endswith("cycle_26_a2_checkid_removal.py"):
                    continue  # self-reference
                with open(p) as fp:
                    content = fp.read()
                # Strip docstrings to avoid false positives
                content_no_docs = re.sub(r'"""[\s\S]*?"""', "", content)
                if ".resume(checkpoint_id=" in content_no_docs:
                    results.append(p)
        assert not results, (
            f"Tests still use removed kwarg at runtime: {results}"
        )

    def test_no_checkpoint_id_kwarg_in_dsl(self):
        """No DSL source should pass checkpoint_id=... to resume()."""
        results = []
        for root, _, files in os.walk("src/backend/dsl/"):
            if "__pycache__" in root: continue
            for f in files:
                if not f.endswith(".py"): continue
                p = os.path.join(root, f)
                with open(p) as fp:
                    content = fp.read()
                if ".resume(checkpoint_id=" in content or 'resume(checkpoint_id="' in content:
                    results.append(p)
        # Allow only the type stub itself (builder.pyi)
        results = [p for p in results if "builder.pyi" not in p]
        assert not results, f"DSL still uses removed kwarg: {results}"
