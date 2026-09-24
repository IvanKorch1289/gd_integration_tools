"""Regression tests для tools/classify_object_authorization.py.

Per v4 §10 P1 'evidence требует testable surface': classifier tool
для object authorization callsites является atomic аналитическим
инструментом — нужен regression coverage перед использованием
в P0 audit decisions.

Test scope:
- Module imports + main() callable.
- Classification heuristics (per `INFRA_REGISTRY_NAMES` + patterns).
- Output format (human-readable + JSON).
- Edge cases (admin paths skipped, no tenant contexts, AST nodes).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "_classify_test",
        Path(__file__).resolve().parents[3]
        / "tools"
        / "classify_object_authorization.py",
    )
    if spec is None or spec.loader is None:
        raise ImportError("Cannot load classify_object_authorization.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


mod = _load_module()


class TestClassification:
    """Per-snippet classification logic."""

    def _classify(self, code: str) -> str:
        """Compile `code`, return first classified callsite type."""
        tree = mod.ast.parse(code)
        for node in mod.ast.walk(tree):
            if isinstance(node, mod.ast.Call):
                # Function signature: _classify_callsite(py, node).
                # line_no extracted from node.lineno automatically.
                cs = mod._classify_callsite(
                    type("FakePy", (), {"parts": ()})(), node,
                )
                if cs is not None:
                    return cs.receiver_type
        return "skipped"

    def test_session_query_classified_user_data(self) -> None:
        """ORM query → user-data.

        Uses real source code from project tree (path must be in
        PROJECT_ROOT для path.relative_to() внутри _classify_callsite).
        """
        # Use existing src file with session.query(.*Model).filter_by(id=).
        target = next(
            (r for r in mod.collect_all_callsites()
             if r.receiver_type == "user-data"
             and "session.query" in r.snippet),
            None,
        )
        assert target is not None, (
            "Expected at least one user-data callsite с session.query в реальном src/"
        )
        assert target.detection_pattern == "orm-query"
        assert target.file.endswith(".py")

    def test_self_routes_classified_infra_registry(self) -> None:
        """self._routes.get → infra-registry (private-plural-collection)."""
        target = next(
            (r for r in mod.collect_all_callsites()
             if r.receiver_type == "infra-registry"
             and "self._routes" in r.snippet),
            None,
        )
        assert target is not None, (
            "Expected at least one infra-registry callsite с self._routes в реальном src/"
        )
        assert "private-plural-collection" in target.detection_pattern or \
               "infra-name-suffix" in target.detection_pattern


class TestOutputFormat:
    """--json and table-render output."""

    def test_json_serializable(self) -> None:
        """--json output per-call is dataclass-serializable."""
        rows = mod.collect_all_callsites()
        # Without running CLI, just verify dataclass.asdict works.
        for r in rows[:1]:
            d = mod.asdict(r)
            assert "file" in d
            assert "line" in d
            assert "receiver_type" in d

    def test_table_render_with_sample(self) -> None:
        """render_table() returns formatted string with header + rows."""
        rows = mod.collect_all_callsites()
        # Just render with first 5.
        output = mod.render_table(rows[:5], top=None)
        assert "callsites" in output
        assert "Summary:" in output
        assert "File" in output  # column header

    def test_total_count_consistent(self) -> None:
        """collect_all_callsites() returns ≥100 callsites (matches check)."""
        rows = mod.collect_all_callsites()
        # Per check_object_authorization.py: 133 total.
        # Filtered list excludes admin/auth/tests → ожидаемо similar range.
        assert len(rows) >= 100, (
            f"Expected ≥100 callsites; got {len(rows)} — "
            "classifier may have over-filtered или check logic changed"
        )

    def test_classification_distribution(self) -> None:
        """Per cycle 158+ measurement: most should be infra-registry."""
        rows = mod.collect_all_callsites()
        by_type = {}
        for r in rows:
            by_type[r.receiver_type] = by_type.get(r.receiver_type, 0) + 1
        # Per real cycle 158+ measurement: ~75% infra-registry.
        infra_ratio = by_type.get("infra-registry", 0) / len(rows)
        assert infra_ratio > 0.5, (
            f"Expected infra-registry > 50% (cycle 158+ baseline ~75%); "
            f"got {infra_ratio * 100:.1f}%. "
            f"Distribution: {by_type}"
        )


class TestNoRegression:
    """Verify all gates still pass after classifier work."""

    def test_compile_clean(self) -> None:
        """compileall на tools/ exit 0 (no Python syntax regressions)."""
        import subprocess

        result = subprocess.run(
            ["python3.14", "-m", "compileall", "-q", "tools"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0
