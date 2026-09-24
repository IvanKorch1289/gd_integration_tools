"""RPA Recorder → DSL Draft generator (Wave 3 #16)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

__all__ = (
    "DSLStep",
    "RPARecorder",
    "RecordedAction",
    "RecorderActionType",
    "export_dsl_draft",
    "generate_route_draft",
    "get_rpa_recorder",
)


class RecorderActionType(StrEnum):
    """Browser action types from recorder."""

    NAVIGATE = "navigate"
    CLICK = "click"
    FILL = "fill"
    SUBMIT = "submit"
    SCREENSHOT = "screenshot"
    WAIT = "wait"
    EXTRACT = "extract"
    ASSERT = "assert"


@dataclass(slots=True)
class RecordedAction:
    """Single recorded browser action."""

    action: str  # RecorderActionType value.
    url: str = ""
    selector: str = ""
    value: str = ""
    description: str = ""
    timeout_seconds: float = 5.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DSLStep:
    """DSL step (used in route.yaml)."""

    name: str
    action: str
    args: dict[str, Any] = field(default_factory=dict)


class RPARecorder:
    """Buffer of recorded actions."""

    def __init__(self) -> None:
        self._actions: list[RecordedAction] = []

    def add_action(self, action: RecordedAction) -> None:
        """Добавить записанное действие в историю сессии."""
        self._actions.append(action)

    def actions(self) -> list[RecordedAction]:
        """Все записанные действия (порядок записи)."""
        return list(self._actions)

    def size(self) -> int:
        """Количество записанных действий."""
        return len(self._actions)

    def clear(self) -> None:
        """Очистить историю записи (новая сессия)."""
        self._actions.clear()


# ─── DSL generation ───────────────────────────────────


def _action_to_dsl_step(idx: int, action: RecordedAction) -> DSLStep:
    """Convert RecordedAction → DSLStep."""
    if action.action == RecorderActionType.NAVIGATE:
        return DSLStep(
            name=f"step_{idx}_navigate", action="browser.open", args={"url": action.url}
        )
    if action.action == RecorderActionType.CLICK:
        return DSLStep(
            name=f"step_{idx}_click",
            action="browser.click",
            args={"selector": action.selector, "timeout": action.timeout_seconds},
        )
    if action.action == RecorderActionType.FILL:
        return DSLStep(
            name=f"step_{idx}_fill",
            action="browser.fill",
            args={"selector": action.selector, "value": action.value},
        )
    if action.action == RecorderActionType.SUBMIT:
        return DSLStep(
            name=f"step_{idx}_submit",
            action="browser.click",
            args={
                "selector": action.selector or "button[type=submit]",
                "timeout": action.timeout_seconds,
            },
        )
    if action.action == RecorderActionType.SCREENSHOT:
        return DSLStep(
            name=f"step_{idx}_screenshot",
            action="browser.screenshot",
            args={"path": action.metadata.get("path", "screenshot.png")},
        )
    if action.action == RecorderActionType.WAIT:
        return DSLStep(
            name=f"step_{idx}_wait",
            action="browser.wait",
            args={"selector": action.selector, "timeout": action.timeout_seconds},
        )
    if action.action == RecorderActionType.EXTRACT:
        return DSLStep(
            name=f"step_{idx}_extract",
            action="browser.extract",
            args={"selector": action.selector, "field": action.value},
        )
    if action.action == RecorderActionType.ASSERT:
        return DSLStep(
            name=f"step_{idx}_assert",
            action="browser.assert",
            args={"selector": action.selector, "expected": action.value},
        )
    return DSLStep(name=f"step_{idx}_unknown", action=action.action, args={})


def parse_recorded_actions(actions: list[RecordedAction]) -> list[DSLStep]:
    """Convert list of recorded actions to DSL steps."""
    return [_action_to_dsl_step(i, a) for i, a in enumerate(actions)]


# ─── Route draft generation ───────────────────────────


def generate_route_draft(
    actions: list[RecordedAction], route_id: str, *, base_url: str = ""
) -> dict[str, str]:
    """Generate route.yaml + test scaffold from recorded actions.

    Returns:
        Dict {file_path: content} for export.
    """
    steps = parse_recorded_actions(actions)
    files: dict[str, str] = {}

    # route.yaml.
    files["route.yaml"] = _render_route_yaml(route_id, steps, base_url, actions)

    # test_scaffold.
    files[f"test_{route_id}.py"] = _render_test_scaffold(route_id, steps)

    return files


def _render_route_yaml(
    route_id: str, steps: list[DSLStep], base_url: str, actions: list[RecordedAction]
) -> str:
    """Render route.yaml content."""
    lines: list[str] = []
    lines.append("# AUTO-GENERATED from RPA recorder. EDIT BEFORE USING.")
    lines.append("# TODO: verify selectors, add assertions, run lint+tests.")
    lines.append("")
    lines.append("[route]")
    lines.append(f'id = "{route_id}"')
    if base_url:
        lines.append(f'source = "browser://{base_url}"')
    else:
        lines.append('source = "rpa://recorded"')
    lines.append(f'description = "Auto-generated from {len(actions)} recorded actions"')
    lines.append('owner = "team-rpa"')
    lines.append('kind = "rpa"')
    lines.append("")
    lines.append("[contract]")
    lines.append("timeout_seconds = 60")
    lines.append('dlq_topic = "events.rpa.{}.dlq"'.format(route_id))
    lines.append("")
    lines.append("[steps]")
    for step in steps:
        lines.append("[[steps.item]]")
        lines.append(f'name = "{step.name}"')
        lines.append(f'action = "{step.action}"')
        for k, v in step.args.items():
            lines.append(f"{k} = {repr(v)}")
        lines.append("")
    return "\n".join(lines)


def _render_test_scaffold(route_id: str, steps: list[DSLStep]) -> str:
    """Render test scaffold."""
    step_names = [s.name for s in steps]
    return f'''"""Test scaffold для {route_id} (auto-generated from RPA).

TODO: Replace with proper assertions + fixtures.
"""

from __future__ import annotations

import pytest


# Generated steps: {step_names}
@pytest.mark.asyncio
async def test_{route_id}_happy_path() -> None:
    \"\"\"Smoke test для recorded actions.\"\"\"
    # TODO: integrate with rpa_runner
    assert True
'''


# ─── Export ───────────────────────────────────────────


def export_dsl_draft(files: dict[str, str], target_dir: str | Path) -> list[Path]:
    """Write generated files в target_dir."""
    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for rel_path, content in files.items():
        full = target / rel_path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")
        written.append(full)
    return written


_recorder: RPARecorder | None = None


def get_rpa_recorder() -> RPARecorder:
    """Singleton-доступ к общему ``RPARecorder``."""
    global _recorder
    if _recorder is None:
        _recorder = RPARecorder()
    return _recorder


def reset_rpa_recorder() -> None:
    """Сбросить singleton (следующий ``get_`` создаст новый)."""
    global _recorder
    _recorder = None
