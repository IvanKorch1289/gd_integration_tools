"""Unit-тесты для dsl_diff helper'ов (S10 K3 W6)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_module():
    path = Path(__file__).resolve().parents[3] / "tools" / "dsl_diff.py"
    spec = importlib.util.spec_from_file_location("_dsl_diff_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


mod = _load_module()


def test_diff_identical_pipelines_returns_empty_changes() -> None:
    pipe = {"route_id": "x", "steps": [{"call_function": {"ref": "m:f"}}]}
    diff = mod._diff_pipelines(pipe, pipe)
    assert diff["added"] == []
    assert diff["removed"] == []
    assert diff["changed"] == []


def test_diff_added_step() -> None:
    before = {"route_id": "x", "steps": [{"step_a": {}}]}
    after = {"route_id": "x", "steps": [{"step_a": {}}, {"step_b": {}}]}
    diff = mod._diff_pipelines(before, after)
    assert len(diff["added"]) == 1
    assert diff["added"][0]["index"] == 1


def test_diff_removed_step() -> None:
    before = {"route_id": "x", "steps": [{"a": {}}, {"b": {}}]}
    after = {"route_id": "x", "steps": [{"a": {}}]}
    diff = mod._diff_pipelines(before, after)
    assert len(diff["removed"]) == 1
    assert diff["removed"][0]["index"] == 1


def test_diff_changed_step() -> None:
    before = {"route_id": "x", "steps": [{"call_function": {"ref": "m:f"}}]}
    after = {"route_id": "x", "steps": [{"call_function": {"ref": "m:g"}}]}
    diff = mod._diff_pipelines(before, after)
    assert len(diff["changed"]) == 1


def test_diff_text_renderer_includes_route_id_change() -> None:
    before = {"route_id": "old", "steps": []}
    after = {"route_id": "new", "steps": []}
    diff = mod._diff_pipelines(before, after)
    text = mod._render_text(diff)
    assert "old" in text and "new" in text
