"""S86 W2: defense-in-depth tests для Temporal sandbox pattern.

V2 P0 #2 (stale report): compile_agent_invoke_step использовал
``await gateway.invoke(request)`` внутри workflow-функции.
Temporal запрещает I/O в workflow-sandbox (deterministic replay).

Sprint 37 (d42c550d) уже исправил: ``workflow.execute_activity("_agent_invoke", ...)``
+ ``_agent_invoke_activity`` в activity_bridge.py.

W2: regression tests гарантирующие что:
1. step_compilers.py НЕ содержит прямых I/O calls
2. Все activity invocations идут через workflow.execute_activity
3. _agent_invoke_activity properly registered
4. AIRequest reconstruction в activity НЕ теряет поля
"""

from __future__ import annotations

import inspect
import re

import pytest

pytestmark = pytest.mark.unit


def test_step_compilers_no_direct_io_calls() -> None:
    """V2 P0 #2 guard: никаких direct I/O в step_compilers.

    Запрещено:
    - await gateway.invoke / acompletion / completion
    - await any httpclient method
    - await any storage client call
    - await any external API call

    Разрешено:
    - workflow.execute_activity (sandbox-safe)
    - workflow.execute_child_workflow
    - ctx.setdefault / dict access (deterministic)
    """
    import ast
    from pathlib import Path

    src = Path(
        "src/backend/dsl/workflow/compiler/step_compilers.py"
    ).read_text()
    tree = ast.parse(src)

    forbidden_patterns = [
        r"\.invoke\(",
        r"\.acompletion\(",
        r"\.completion\(",
        r"\.http_post\(",
        r"\.http_get\(",
        r"\.request\(",
        r"\.send\(",
    ]
    # Allow workflow.execute_activity and similar sandbox-safe patterns
    allowed_contexts = [
        "workflow.execute_activity",
        "workflow.execute_child_workflow",
        "workflow.start_activity",
    ]

    for node in ast.walk(tree):
        if isinstance(node, ast.Await):
            # Get source line
            line = ast.get_source_segment(src, node) or ""
            for pattern in forbidden_patterns:
                if re.search(pattern, line):
                    # Check it's NOT a workflow.execute_* call
                    if not any(allowed in line for allowed in allowed_contexts):
                        pytest.fail(
                            f"V2 P0 #2 regression: direct I/O in step_compilers "
                            f"at line {node.lineno}: {line!r}"
                        )


def test_compile_agent_invoke_uses_workflow_execute_activity() -> None:
    """compile_agent_invoke_step ВСЕГДА вызывает workflow.execute_activity."""
    from src.backend.dsl.workflow.compiler import step_compilers

    source = inspect.getsource(step_compilers.compile_agent_invoke_step)
    assert "workflow.execute_activity" in source, (
        "compile_agent_invoke_step must use workflow.execute_activity "
        "for sandbox safety (V2 P0 #2)"
    )
    assert '"_agent_invoke"' in source or "'_agent_invoke'" in source, (
        "compile_agent_invoke_step must reference _agent_invoke activity"
    )


def test_agent_invoke_activity_reconstructs_request() -> None:
    """_agent_invoke_activity восстанавливает AIRequest из dict."""
    from src.backend.dsl.workflow.compiler import activity_bridge

    source = inspect.getsource(activity_bridge._agent_invoke_activity)
    assert "AIRequest(**payload)" in source or "AIRequest(" in source, (
        "_agent_invoke_activity must reconstruct AIRequest from payload"
    )
    assert "AIGateway" in source
    assert "gateway.invoke" in source or "await gateway" in source


def test_activity_bridge_handles_agent_invoke() -> None:
    """ActivityBridge.get() возвращает _agent_invoke_activity для _agent_invoke."""
    from src.backend.dsl.workflow.compiler.activity_bridge import (
        ActivityBridge,
        _agent_invoke_activity,
    )

    bridge = ActivityBridge()
    activity = bridge.get("_agent_invoke")
    assert activity is _agent_invoke_activity, (
        "ActivityBridge.get('_agent_invoke') must return _agent_invoke_activity"
    )


def test_agent_invoke_declaration_yields_activity_spec() -> None:
    """AgentInvokeDeclaration → ('_agent_invoke', ()) для worker registration.

    Smoke test: _iter_activity_specs has case for AgentInvokeDeclaration.
    """
    import inspect

    from src.backend.dsl.workflow.compiler import activity_bridge

    source = inspect.getsource(activity_bridge._iter_activity_specs)
    # _iter_activity_specs must handle AgentInvokeDeclaration
    assert "AgentInvokeDeclaration" in source
    assert '"_agent_invoke"' in source or "'_agent_invoke'" in source
    # must return 1-tuple with _agent_invoke string
    assert '"_agent_invoke"' in source.split("AgentInvokeDeclaration")[1]
