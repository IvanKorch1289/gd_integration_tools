"""Focused tests for ``core.rpa_recorder`` (Wave 3 #16)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.backend.core.rpa_recorder import (
    DSLStep,
    RecordedAction,
    RecorderActionType,
    RPARecorder,
    export_dsl_draft,
    generate_route_draft,
    get_rpa_recorder,
    parse_recorded_actions,
)
from src.backend.core.rpa_recorder.recorder import reset_rpa_recorder


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_rpa_recorder()


class TestRecorderActionType:
    def test_values(self) -> None:
        assert RecorderActionType.NAVIGATE.value == "navigate"
        assert RecorderActionType.CLICK.value == "click"
        assert RecorderActionType.FILL.value == "fill"
        assert RecorderActionType.SUBMIT.value == "submit"
        assert RecorderActionType.SCREENSHOT.value == "screenshot"
        assert RecorderActionType.WAIT.value == "wait"
        assert RecorderActionType.EXTRACT.value == "extract"
        assert RecorderActionType.ASSERT.value == "assert"


class TestRecordedAction:
    def test_defaults(self) -> None:
        a = RecordedAction(action="navigate")
        assert a.url == ""
        assert a.selector == ""
        assert a.value == ""
        assert a.timeout_seconds == 5.0


class TestDSLStep:
    def test_init(self) -> None:
        s = DSLStep(name="step1", action="browser.click", args={"selector": "#btn"})
        assert s.args == {"selector": "#btn"}


class TestRecorder:
    def test_init(self) -> None:
        r = RPARecorder()
        assert r.size() == 0
        assert r.actions() == []

    def test_add_action(self) -> None:
        r = RPARecorder()
        r.add_action(RecordedAction(action="navigate", url="https://x.com"))
        assert r.size() == 1
        assert r.actions()[0].url == "https://x.com"

    def test_actions_returns_copy(self) -> None:
        r = RPARecorder()
        r.add_action(RecordedAction(action="navigate"))
        actions = r.actions()
        actions.clear()
        # Internal list unchanged.
        assert r.size() == 1

    def test_clear(self) -> None:
        r = RPARecorder()
        r.add_action(RecordedAction(action="navigate"))
        r.clear()
        assert r.size() == 0


class TestParseRecordedActions:
    def test_empty(self) -> None:
        assert parse_recorded_actions([]) == []

    def test_navigate(self) -> None:
        actions = [RecordedAction(action="navigate", url="https://example.com")]
        steps = parse_recorded_actions(actions)
        assert steps[0].name == "step_0_navigate"
        assert steps[0].action == "browser.open"
        assert steps[0].args == {"url": "https://example.com"}

    def test_click(self) -> None:
        actions = [RecordedAction(action="click", selector="#submit", timeout_seconds=3.0)]
        steps = parse_recorded_actions(actions)
        assert steps[0].name == "step_0_click"
        assert steps[0].action == "browser.click"
        assert steps[0].args == {"selector": "#submit", "timeout": 3.0}

    def test_fill(self) -> None:
        actions = [
            RecordedAction(action="fill", selector="input#q", value="hello")
        ]
        steps = parse_recorded_actions(actions)
        assert steps[0].action == "browser.fill"
        assert steps[0].args == {"selector": "input#q", "value": "hello"}

    def test_submit(self) -> None:
        actions = [RecordedAction(action="submit", selector="button.send")]
        steps = parse_recorded_actions(actions)
        assert steps[0].action == "browser.click"
        assert steps[0].args["selector"] == "button.send"

    def test_screenshot(self) -> None:
        actions = [RecordedAction(
            action="screenshot",
            metadata={"path": "evidence.png"},
        )]
        steps = parse_recorded_actions(actions)
        assert steps[0].action == "browser.screenshot"
        assert steps[0].args == {"path": "evidence.png"}

    def test_wait(self) -> None:
        actions = [
            RecordedAction(action="wait", selector=".loaded", timeout_seconds=10.0)
        ]
        steps = parse_recorded_actions(actions)
        assert steps[0].action == "browser.wait"
        assert steps[0].args == {"selector": ".loaded", "timeout": 10.0}

    def test_extract(self) -> None:
        actions = [
            RecordedAction(action="extract", selector=".price", value="price")
        ]
        steps = parse_recorded_actions(actions)
        assert steps[0].action == "browser.extract"

    def test_assert(self) -> None:
        actions = [
            RecordedAction(action="assert", selector=".success", value="Order placed")
        ]
        steps = parse_recorded_actions(actions)
        assert steps[0].action == "browser.assert"
        assert steps[0].args == {"selector": ".success", "expected": "Order placed"}

    def test_unknown_action(self) -> None:
        actions = [RecordedAction(action="weird_action")]
        steps = parse_recorded_actions(actions)
        assert steps[0].name == "step_0_unknown"
        assert steps[0].action == "weird_action"

    def test_multiple_actions(self) -> None:
        actions = [
            RecordedAction(action="navigate", url="https://x.com"),
            RecordedAction(action="fill", selector="input", value="q"),
            RecordedAction(action="click", selector="button"),
        ]
        steps = parse_recorded_actions(actions)
        assert len(steps) == 3
        assert [s.name for s in steps] == [
            "step_0_navigate", "step_1_fill", "step_2_click"
        ]


class TestGenerateRouteDraft:
    def test_basic(self) -> None:
        actions = [
            RecordedAction(action="navigate", url="https://example.com"),
            RecordedAction(action="fill", selector="input#q", value="hello"),
            RecordedAction(action="click", selector="button.search"),
        ]
        files = generate_route_draft(actions, route_id="search-flow")
        assert "route.yaml" in files
        assert "test_search-flow.py" in files

    def test_route_yaml_content(self) -> None:
        actions = [
            RecordedAction(action="navigate", url="https://x.com"),
            RecordedAction(action="click", selector="button"),
        ]
        files = generate_route_draft(actions, route_id="r1")
        yaml = files["route.yaml"]
        assert "[route]" in yaml
        assert 'id = "r1"' in yaml
        assert "[contract]" in yaml
        assert "[steps]" in yaml
        assert "step_0_navigate" in yaml
        assert "step_1_click" in yaml
        assert "browser.open" in yaml
        assert "browser.click" in yaml
        assert "AUTO-GENERATED" in yaml  # TODO marker
        assert "TODO:" in yaml  # verification reminder

    def test_route_yaml_with_base_url(self) -> None:
        actions = [RecordedAction(action="navigate", url="https://x.com")]
        files = generate_route_draft(
            actions, route_id="r1", base_url="https://api.x.com"
        )
        yaml = files["route.yaml"]
        assert "browser://https://api.x.com" in yaml

    def test_test_scaffold(self) -> None:
        actions = [RecordedAction(action="navigate")]
        files = generate_route_draft(actions, route_id="search-flow")
        test = files["test_search-flow.py"]
        assert "test_search-flow_happy_path" in test
        assert "smoke" in test.lower()
        assert "import pytest" in test

    def test_empty_actions(self) -> None:
        files = generate_route_draft([], route_id="empty")
        assert "route.yaml" in files


class TestExportDSDLDraft:
    def test_export(self, tmp_path: Path) -> None:
        files = {
            "route.yaml": "content1",
            "test_r1.py": "content2",
        }
        written = export_dsl_draft(files, tmp_path / "extensions" / "r1")
        assert len(written) == 2
        assert (tmp_path / "extensions" / "r1" / "route.yaml").exists()

    def test_export_creates_nested_dirs(self, tmp_path: Path) -> None:
        files = {"deep/nested/file.txt": "x"}
        written = export_dsl_draft(files, tmp_path / "out")
        assert (tmp_path / "out" / "deep" / "nested" / "file.txt").exists()


class TestSingleton:
    def test_singleton(self) -> None:
        r1 = get_rpa_recorder()
        r2 = get_rpa_recorder()
        assert r1 is r2

    def test_reset(self) -> None:
        r1 = get_rpa_recorder()
        reset_rpa_recorder()
        r2 = get_rpa_recorder()
        assert r1 is not r2


class TestExports:
    def test_module_all(self) -> None:
        from src.backend.core import rpa_recorder

        assert len(rpa_recorder.__all__) == 8


class TestRealisticExample:
    """Realistic: search flow from recorded actions."""

    def test_search_flow_recording(self, tmp_path: Path) -> None:
        recorder = get_rpa_recorder()
        # Simulate Playwright recording:
        recorder.add_action(RecordedAction(
            action="navigate", url="https://search.example.com",
        ))
        recorder.add_action(RecordedAction(
            action="fill", selector="input[name=q]", value="RPA integration",
        ))
        recorder.add_action(RecordedAction(
            action="click", selector="button[type=submit]",
        ))
        recorder.add_action(RecordedAction(
            action="wait", selector=".results", timeout_seconds=10.0,
        ))
        recorder.add_action(RecordedAction(
            action="extract", selector=".result-count", value="total_count",
        ))
        recorder.add_action(RecordedAction(
            action="assert", selector=".result-count", value="42",
        ))

        # Generate DSL draft.
        files = generate_route_draft(
            recorder.actions(),
            route_id="search-flow",
            base_url="https://search.example.com",
        )
        target = tmp_path / "extensions" / "search-flow"
        written = export_dsl_draft(files, target)
        assert (target / "route.yaml").exists()
        assert (target / "test_search-flow.py").exists()

        # Verify route.yaml content.
        yaml = (target / "route.yaml").read_text()
        assert "search-flow" in yaml
        assert "browser.open" in yaml
        assert "browser.fill" in yaml
        assert "browser.click" in yaml
        assert "browser.wait" in yaml
        assert "browser.extract" in yaml
        assert "browser.assert" in yaml
        assert "browser://https://search.example.com" in yaml
        # 6 steps.
        assert yaml.count("[[steps.item]]") == 6
