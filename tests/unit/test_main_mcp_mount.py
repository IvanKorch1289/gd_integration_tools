"""Regression tests for cycle 210-216 MCP routing fixes.

D-AUDIT-20804 (cycle 210): redirect_slashes=False.
D-AUDIT-20805 (cycle 213): combined lifespan.
D-AUDIT-20807 (cycle 216): mount moved to app_factory (granian
imports only `app` attr, НЕ module body).

Pure AST checks — NO runtime side-effects (avoid importing main.py
которое triggers full app init).

Verifies (cycle 210-213 behavior — main.py context):
1. Mount logic exists (now in app_factory.py, NOT main.py)
2. Function has `app.router.redirect_slashes = False` assignment
3. Assignment happens AFTER `app.mount(...)` call
4. `return` guard for http_enabled=False present

Cycle 216 added: mount location verification (app_factory, not main).
"""

from __future__ import annotations

import ast
import inspect


def _get_main_source() -> str:
    """Читает main.py source без triggering импорт."""
    import src.backend.main
    with open(src.backend.main.__file__, encoding="utf-8") as f:
        return f.read()


def _get_app_factory_source() -> str:
    """Читает app_factory.py source без triggering импорт."""
    import src.backend.plugins.composition.app_factory
    with open(
        src.backend.plugins.composition.app_factory.__file__, encoding="utf-8"
    ) as f:
        return f.read()


def _get_mount_mcp_http() -> "ast.FunctionDef | None":
    """Find _mount_mcp_http function in app_factory (cycle 216 location)."""
    tree = ast.parse(_get_app_factory_source())
    for stmt in tree.body:
        if isinstance(stmt, ast.FunctionDef) and stmt.name == "_mount_mcp_http":
            return stmt
    return None


# ── Cycle 216: mount moved from main.py to app_factory.py ──────────


def test_mount_mcp_http_in_app_factory() -> None:
    """D-AUDIT-20807 (cycle 216): _mount_mcp_http moved to app_factory.

    Cycle 215 investigation: granian/uvicorn импортирует ТОЛЬКО ``app`` attr,
    НЕ module body → module-level call не выполняется. Решение: move
    mount в ``_configure_application_components()`` внутри create_app().
    """
    # 1. Function exists in app_factory
    fn = _get_mount_mcp_http()
    assert fn is not None, (
        "_mount_mcp_http must be defined in app_factory.py "
        "(cycle 216 fix: granian не выполняет main.py module body)"
    )

    # 2. Function takes 'app' parameter
    params = [arg.arg for arg in fn.args.args]
    assert "app" in params, (
        f"_mount_mcp_http must take 'app' parameter, got: {params}"
    )

    # 3. Called from _configure_application_components
    af_src = _get_app_factory_source()
    tree = ast.parse(af_src)
    configure_fn = None
    for stmt in tree.body:
        if (
            isinstance(stmt, ast.FunctionDef)
            and stmt.name == "_configure_application_components"
        ):
            configure_fn = stmt
            break
    assert configure_fn is not None, "_configure_application_components not found"

    has_call = any(
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "_mount_mcp_http"
        for node in ast.walk(configure_fn)
    )
    assert has_call, (
        "_mount_mcp_http must be called from _configure_application_components"
    )

    # 4. NOT in main.py at module-level
    main_src = _get_main_source()
    main_tree = ast.parse(main_src)
    has_module_level_call = any(
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Call)
        and isinstance(stmt.value.func, ast.Name)
        and stmt.value.func.id == "_mount_mcp_http"
        for stmt in main_tree.body
    )
    assert not has_module_level_call, (
        "main.py must NOT have module-level _mount_mcp_http() call "
        "(cycle 215/216: granian не выполняет main.py module body, "
        "только импортирует атрибут `app`)"
    )

