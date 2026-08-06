"""D-AUDIT-C-W3.6 test — tools/blue_green.sh switch command idempotency + reload flag.

Per D-AUDIT-C-W3.6 (Sprint 183 W3) + D-LESSON-11: pre-fix ``cmd_switch``
только обновлял state-файл без nginx reload. Post-fix: nginx reload
optional через ``BLUE_GREEN_RELOAD_NGINX=1`` env var (default OFF for dev/CI
safety). Если nginx или docker в PATH — reload attempt; иначе warning.

State file path WARNING: blue_green.sh hard-codes state path in
``${PROJECT_ROOT}/.blue_green.state`` (project root, not cwd). For tests
we need to override state path via symlink or fixture. Using cwd-based
script-wrapper hack (we set STATE via copy+run-from-tmp).

Strict-test policy per D-LESSON-11: NO lax `with x: pass`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_SCRIPT = REPO_ROOT / "tools" / "blue_green.sh"


def _setup_isolated_script() -> Path:
    """Copy script to temp dir + cleanup any pre-existing state.

    The blue_green.sh script writes state to ``${PROJECT_ROOT}/.blue_green.state``
    where PROJECT_ROOT = parent of script. If we copy script to
    ``/tmp/X/blue_green.sh``, then ``PROJECT_ROOT=/tmp`` (parent of X).
    All tests share ``/tmp/.blue_green.state`` → cross-contamination.
    Fix: clean up ``/tmp/.blue_green.state`` at start AND end of every test.
    """
    # Pre-cleanup: remove shared state file at parent-of-tmpdir level
    # (we don't know which tmpdir will be picked, so this is best-effort)
    tmpdir = Path(tempfile.mkdtemp(prefix="blue_green_test_"))
    script_copy = tmpdir / "blue_green.sh"
    shutil.copy(SRC_SCRIPT, script_copy)
    os.chmod(script_copy, 0o755)
    return script_copy


def _clean_shared_state():
    """Remove the global state file at ``/tmp/.blue_green.state``.

    The blue_green.sh hard-codes state location to PROJECT_ROOT which
    resolves to /tmp (parent of mkdtemp). All tests share this file —
    explicit cleanup before/after each test prevents cross-contamination.
    """
    Path("/tmp/.blue_green.state").unlink(missing_ok=True)


import pytest


@pytest.fixture(autouse=True)
def _clean_state_file():
    """Per-test fixture: ensure /tmp/.blue_green.state is clean.

    blue_green.sh hard-codes state to PROJECT_ROOT which resolves to /tmp
    regardless of cwd. Without this fixture, tests would share state and
    produce cross-contamination.
    """
    _clean_shared_state()
    yield
    _clean_shared_state()


def _run(script_path: Path, args: list, env: dict, cwd: Path):
    """Helper to invoke isolated script copy with custom env + cwd."""
    return subprocess.run(
        ["bash", str(script_path), *args],
        env={**os.environ, **env},
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )


def test_switch_writes_state_file():
    """``switch green`` обновляет .blue_green.state файл (default state-only mode)."""
    script = _setup_isolated_script()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            result = _run(
                script,
                ["switch", "green"],
                {"BLUE_GREEN_RELOAD_NGINX": "0"},
                cwd=Path(tmp),
            )
            assert result.returncode == 0, (
                f"Expected exit 0, got {result.returncode}\nstderr: {result.stderr}"
            )
            state_file = script.parent.parent / ".blue_green.state"
            assert state_file.exists()
            assert state_file.read_text() == "green"
            assert "nginx reload skipped" in result.stderr
    finally:
        (script.parent.parent / ".blue_green.state").unlink(missing_ok=True)
        shutil.rmtree(script.parent, ignore_errors=True)


def test_switch_idempotent_on_same_target():
    """Повторный switch на ту же target = no-op (state остаётся)."""
    script = _setup_isolated_script()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            _run(script, ["switch", "green"], {"BLUE_GREEN_RELOAD_NGINX": "0"}, cwd=Path(tmp))
            result = _run(
                script, ["switch", "green"], {"BLUE_GREEN_RELOAD_NGINX": "0"}, cwd=Path(tmp)
            )
            assert result.returncode == 0
            assert "already on green" in result.stderr
            assert (script.parent.parent / ".blue_green.state").read_text() == "green"
    finally:
        (script.parent.parent / ".blue_green.state").unlink(missing_ok=True)
        shutil.rmtree(script.parent, ignore_errors=True)


def test_switch_with_reload_flag_attempts_nginx():
    """``BLUE_GREEN_RELOAD_NGINX=1`` пытается reload, fallback gracefully."""
    script = _setup_isolated_script()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            env_stripped = {
                "BLUE_GREEN_RELOAD_NGINX": "1",
                # PATH must still contain `bash` (so subprocess can run script).
                # Use a minimal PATH that excludes nginx + docker but keeps bash.
                "PATH": "/usr/bin:/bin",
            }
            result = _run(script, ["switch", "green"], env_stripped, cwd=Path(tmp))
            assert result.returncode == 0
            assert (script.parent.parent / ".blue_green.state").read_text() == "green"
            assert (
                "neither nginx nor docker in PATH" in result.stderr
                or "WARN" in result.stderr
            )
    finally:
        (script.parent.parent / ".blue_green.state").unlink(missing_ok=True)
        shutil.rmtree(script.parent, ignore_errors=True)


def test_switch_blue_then_green_state_progression():
    """Blue → Green → Blue state progression работает (state is just replaced)."""
    script = _setup_isolated_script()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            for target in ("green", "blue", "green"):
                result = _run(
                    script,
                    ["switch", target],
                    {"BLUE_GREEN_RELOAD_NGINX": "0"},
                    cwd=Path(tmp),
                )
                assert result.returncode == 0
                assert (script.parent.parent / ".blue_green.state").read_text() == target
    finally:
        (script.parent.parent / ".blue_green.state").unlink(missing_ok=True)
        shutil.rmtree(script.parent, ignore_errors=True)


def test_status_returns_active_stack():
    """``status`` печатает активный stack (default 'blue' если state отсутствует)."""
    script = _setup_isolated_script()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            result = _run(script, ["status"], {}, cwd=Path(tmp))
            assert result.returncode == 0
            assert "active stack: blue" in result.stdout

            _run(script, ["switch", "green"], {"BLUE_GREEN_RELOAD_NGINX": "0"}, cwd=Path(tmp))
            result = _run(script, ["status"], {}, cwd=Path(tmp))
            assert result.returncode == 0
            assert "active stack: green" in result.stdout
    finally:
        (script.parent.parent / ".blue_green.state").unlink(missing_ok=True)
        shutil.rmtree(script.parent, ignore_errors=True)


def test_invalid_stack_name_rejected():
    """Invalid stack name → die (non-zero exit, error message)."""
    script = _setup_isolated_script()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            result = _run(script, ["switch", "purple"], {}, cwd=Path(tmp))
            assert result.returncode != 0
            assert "must be blue or green" in result.stderr
            assert not (script.parent.parent / ".blue_green.state").exists()
    finally:
        (script.parent.parent / ".blue_green.state").unlink(missing_ok=True)
        shutil.rmtree(script.parent, ignore_errors=True)


def test_no_command_shows_usage_and_fails():
    """``./blue_green.sh`` без аргументов → usage + exit 1."""
    script = _setup_isolated_script()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            result = _run(script, [], {}, cwd=Path(tmp))
            assert result.returncode == 1
            assert "Usage:" in result.stdout
    finally:
        (script.parent.parent / ".blue_green.state").unlink(missing_ok=True)
        shutil.rmtree(script.parent, ignore_errors=True)
