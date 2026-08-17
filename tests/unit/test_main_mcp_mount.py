"""Regression tests for cycle 210 MCP routing fix (D-AUDIT-20804).

Pure AST checks — NO runtime side-effects (avoid importing main.py
которое triggers full app init).

Verifies:
1. main.py содержит \`_mount_mcp_http()\` function
2. Function имеет \`app.router.redirect_slashes = False\` assignment
   (D-AUDIT-20804 cycle 210 fix)
3. Assignment происходит ПОСЛЕ \`app.mount(...)\` call
   (порядок критичен — mount создаёт router, redirect_slashes=False
   должен быть после)
4. \`return\` guard для http_enabled=False присутствует

Ponytail/YAGNI: минимальный fix + минимальный test coverage.
"""

from __future__ import annotations

import ast


def _get_main_source() -> str:
    """Читает main.py source без triggering импорт."""
    import src.backend.main
    with open(src.backend.main.__file__, encoding="utf-8") as f:
        return f.read()


def test_mount_mcp_http_function_exists() -> None:
    """main.py определяет \`_mount_mcp_http()\` function."""
    tree = ast.parse(_get_main_source())
    function_names = [
        stmt.name
        for stmt in tree.body
        if isinstance(stmt, ast.FunctionDef)
    ]
    assert "_mount_mcp_http" in function_names, (
        "_mount_mcp_http function not found in main.py; "
        "MCP HTTP transport mount отсутствует"
    )


def test_redirect_slashes_false_assignment_present() -> None:
    """D-AUDIT-20804: \`app.router.redirect_slashes = False\` в _mount_mcp_http.

    Cycle 210 Ponytail fix — без него Starlette делает 307 redirect
    /mcp → /mcp/ который FastMCP 3.x route (только /mcp) НЕ резолвит.
    """
    tree = ast.parse(_get_main_source())

    redirect_slashes_false_lines = []
    for stmt in tree.body:
        if isinstance(stmt, ast.FunctionDef) and stmt.name == "_mount_mcp_http":
            for assign in (
                node for node in ast.walk(stmt) if isinstance(node, ast.Assign)
            ):
                for target in assign.targets:
                    if (
                        isinstance(target, ast.Attribute)
                        and target.attr == "redirect_slashes"
                        and isinstance(assign.value, ast.Constant)
                        and assign.value.value is False
                    ):
                        redirect_slashes_false_lines.append(assign.lineno)

    assert redirect_slashes_false_lines, (
        "_mount_mcp_http must include "
        "`app.router.redirect_slashes = False` assignment "
        "(D-AUDIT-20804 cycle 210 fix)"
    )


def test_redirect_slashes_after_mount_call() -> None:
    """redirect_slashes=False устанавливается ПОСЛЕ \`app.mount(...)\` call.

    Порядок критичен: redirect_slashes — attribute router'а, который
    после Mount созданного sub-router'а. Если set before Mount, может
    не apply to mount subapp routing.
    """
    tree = ast.parse(_get_main_source())

    for stmt in tree.body:
        if isinstance(stmt, ast.FunctionDef) and stmt.name == "_mount_mcp_http":
            mount_call_line = None
            redirect_slashes_line = None

            for node in ast.walk(stmt):
                # Находим вызов .mount(...)
                if isinstance(node, ast.Call):
                    func = node.func
                    if (
                        isinstance(func, ast.Attribute)
                        and func.attr == "mount"
                    ):
                        mount_call_line = node.lineno
                # Находим assignment redirect_slashes = False
                elif isinstance(node, ast.Assign):
                    for target in node.targets:
                        if (
                            isinstance(target, ast.Attribute)
                            and target.attr == "redirect_slashes"
                            and isinstance(node.value, ast.Constant)
                            and node.value.value is False
                        ):
                            redirect_slashes_line = node.lineno

            assert mount_call_line is not None, (
                "app.mount(...) call not found"
            )
            assert redirect_slashes_line is not None, (
                "redirect_slashes=False assignment not found"
            )
            assert redirect_slashes_line > mount_call_line, (
                f"redirect_slashes=False (line {redirect_slashes_line}) "
                f"must be AFTER app.mount() call (line {mount_call_line}); "
                "set order matters — Mount creates router, redirect_slashes "
                "attribute must be set after Mount registered"
            )


def test_http_enabled_guard_present() -> None:
    """\`if not mcp_settings.http_enabled: return\` guard в _mount_mcp_http."""
    tree = ast.parse(_get_main_source())

    for stmt in tree.body:
        if isinstance(stmt, ast.FunctionDef) and stmt.name == "_mount_mcp_http":
            has_guard = False
            for node in ast.walk(stmt):
                if isinstance(node, ast.If):
                    test = node.test
                    if (
                        isinstance(test, ast.UnaryOp)
                        and isinstance(test.op, ast.Not)
                        and isinstance(test.operand, ast.Attribute)
                        and test.operand.attr == "http_enabled"
                    ):
                        # Check return in body
                        if any(
                            isinstance(s, ast.Return) for s in node.body
                        ):
                            has_guard = True
                            break

            assert has_guard, (
                "_mount_mcp_http must guard on http_enabled flag with "
                "early return; otherwise mount runs on every import even "
                "when feature disabled"
            )
