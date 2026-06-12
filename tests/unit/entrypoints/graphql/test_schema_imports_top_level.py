"""S69 W3: tests для graphql/schema.py top-level dsl imports.

Проверяют:
1. AST-based: zero lazy dsl imports ВНУТРИ resolver methods
2. Top-level imports: route_registry, action_handler_registry, get_tracer
3. 4 dsl imports consolidated at top (route_registry + action_handler_registry + get_tracer + get_dsl_service)
4. No duplicate dsl imports в module
"""

from __future__ import annotations

import ast
from pathlib import Path


def _parse_schema() -> ast.Module:
    return ast.parse(Path("src/backend/entrypoints/graphql/schema.py").read_text())


def test_no_lazy_dsl_imports_in_resolvers() -> None:
    """AST verify: zero `from src.backend.dsl` imports inside functions.

    До S69 W3: 4 lazy imports (lines 306, 313, 429, 446) ВНУТРИ resolver methods.
    После: top-level imports only.
    """
    tree = _parse_schema()
    lazy_imports = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if "src.backend.dsl" in node.module:
                # Check if it's top-level (child of Module) or lazy (in Function)
                # Walk parents: if any Function/AsyncFunction contains this node, it's lazy
                for parent in ast.walk(tree):
                    if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if node in ast.walk(parent):
                            lazy_imports.append((node.lineno, node.module))
                            break

    assert lazy_imports == [], (
        f"Found {len(lazy_imports)} lazy dsl imports: {lazy_imports}. "
        f"Should be top-level only (S69 W3 refactor)."
    )


def test_top_level_dsl_imports() -> None:
    """Top-level imports section содержит 4 dsl modules."""
    source = Path("src/backend/entrypoints/graphql/schema.py").read_text()
    # First 30 lines (top-level imports before any class def)
    top_section = "\n".join(source.split("\n")[:30])

    # All 4 dsl modules должны быть в top-level
    assert "from src.backend.dsl.service import get_dsl_service" in top_section
    assert "from src.backend.dsl.registry import route_registry" in top_section
    assert (
        "from src.backend.dsl.commands.registry import action_handler_registry"
        in top_section
    )
    assert "from src.backend.dsl.engine.tracer import get_tracer" in top_section


def test_no_duplicate_dsl_imports() -> None:
    """No duplicate dsl module imports (был get_tracer imported 2x)."""
    source = Path("src/backend/entrypoints/graphql/schema.py").read_text()
    dsl_imports = source.count("from src.backend.dsl")
    # Should be 4 (one per module: service, registry, commands.registry, engine.tracer)
    assert dsl_imports == 4, (
        f"Found {dsl_imports} `from src.backend.dsl` imports, expected 4"
    )


def test_dsl_names_callable() -> None:
    """All 4 imported dsl names are accessible and callable."""
    from src.backend.dsl.commands.registry import action_handler_registry
    from src.backend.dsl.engine.tracer import get_tracer
    from src.backend.dsl.registry import route_registry
    from src.backend.dsl.service import get_dsl_service

    assert callable(get_dsl_service)
    assert route_registry is not None
    assert action_handler_registry is not None
    assert callable(get_tracer)


def test_get_dsl_service_call_works() -> None:
    """get_dsl_service() returns non-None service."""
    from src.backend.dsl.service import get_dsl_service

    service = get_dsl_service()
    assert service is not None
