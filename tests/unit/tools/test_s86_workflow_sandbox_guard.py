"""S86 W2 — Regression tests для workflow sandbox guard analyzer.

Покрывает:
  * compile_*_step WITHOUT direct I/O → 0 violations
  * compile_*_step WITH gateway.invoke() → 1 violation
  * compile_*_step WITH asyncio.sleep() → 1 violation
  * compile_*_step WITH time.time() → 1 violation
  * code OUTSIDE compile_*_step (e.g. _agent_invoke_activity) → 0 violations
  * SAFE workflow.execute_activity → 0 violations
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from tools.s86_workflow_sandbox_guard import scan_file


@pytest.fixture
def tmp_py_file(tmp_path: Path) -> Path:
    return tmp_path / "test_module.py"


def test_no_violation_when_workflow_safe(tmp_py_file: Path) -> None:
    """compile_*_step using workflow.execute_activity → 0 violations."""
    tmp_py_file.write_text(
        textwrap.dedent(
            """\
            async def compile_activity_step(decl, ctx):
                from temporalio import workflow
                result = await workflow.execute_activity(
                    decl.name, payload, start_to_close_timeout=...
                )
                return result
            """
        )
    )
    assert scan_file(tmp_py_file) == []


def test_violation_direct_gateway_invoke(tmp_py_file: Path) -> None:
    """compile_*_step with ``await gateway.invoke(...)`` → violation."""
    tmp_py_file.write_text(
        textwrap.dedent(
            """\
            async def compile_agent_step(decl, ctx):
                result = await gateway.invoke({"prompt": "hi"})
                return result
            """
        )
    )
    violations = scan_file(tmp_py_file)
    assert len(violations) == 1
    _line_no, _line, reason = violations[0]
    assert "gateway" in reason.lower()


def test_violation_asyncio_sleep(tmp_py_file: Path) -> None:
    """``asyncio.sleep`` inside compile_*_step → violation."""
    tmp_py_file.write_text(
        textwrap.dedent(
            """\
            async def compile_sleep_step(decl, ctx):
                import asyncio
                await asyncio.sleep(5)
                return None
            """
        )
    )
    violations = scan_file(tmp_py_file)
    assert len(violations) == 1
    _line_no, _line, reason = violations[0]
    assert "asyncio.sleep" in reason


def test_violation_time_now(tmp_py_file: Path) -> None:
    """``time.time()`` inside compile_*_step → violation (non-deterministic clock)."""
    tmp_py_file.write_text(
        textwrap.dedent(
            """\
            async def compile_step(decl, ctx):
                import time
                now = time.time()
                return now
            """
        )
    )
    violations = scan_file(tmp_py_file)
    assert len(violations) == 1
    _line_no, _line, reason = violations[0]
    assert "clock" in reason.lower() or "uuid" in reason.lower()


def test_no_violation_outside_compile_step(tmp_py_file: Path) -> None:
    """Code in regular functions (e.g. activity handlers) is not scanned."""
    tmp_py_file.write_text(
        textwrap.dedent(
            """\
            async def _agent_invoke_activity(request):
                # This runs as Temporal ACTIVITY, not workflow — direct I/O OK.
                result = await gateway.invoke(request)
                return result
            """
        )
    )
    assert scan_file(tmp_py_file) == []


def test_workflow_sleep_allowed(tmp_py_file: Path) -> None:
    """``workflow.sleep`` is in safe list → 0 violations."""
    tmp_py_file.write_text(
        textwrap.dedent(
            """\
            async def compile_sleep_step(decl, ctx):
                from temporalio import workflow
                await workflow.sleep(timedelta(seconds=decl.duration_s))
                return None
            """
        )
    )
    assert scan_file(tmp_py_file) == []


def test_multiple_violations_same_function(tmp_py_file: Path) -> None:
    """Multiple violations in same function → multiple reports."""
    tmp_py_file.write_text(
        textwrap.dedent(
            """\
            async def compile_evil_step(decl, ctx):
                import asyncio
                import time
                await gateway.invoke(decl.payload)
                await asyncio.sleep(5)
                now = time.time()
                return now
            """
        )
    )
    violations = scan_file(tmp_py_file)
    assert len(violations) == 3
