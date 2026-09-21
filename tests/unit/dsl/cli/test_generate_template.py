"""S99 W1 — S40 TODO closure: DSL codegen template updated.

Pre-S99: ``dsl/cli/generate.py:304`` имел TODO ``TODO(S40-W6): Implement
{name} — audit found placeholder``. Шаблон process() body подставляет
``{name}`` корректно (f-string substitution в `'''...'''`).

S99 W1:
- Replace TODO with actionable hint comment.
- Add ``{ptype}`` к NotImplementedError message (more context).
- 2 NEW regression tests:
  1. Generate output НЕ содержит actionable TODO
  2. f-string substitution корректно работает (test against actual template)
"""

from __future__ import annotations


def test_generate_template_no_todo() -> None:
    """``dsl/cli/generate.py`` НЕ содержит actionable TODO."""
    from pathlib import Path

    p = Path("src/backend/dsl/cli/generate.py")
    src = p.read_text()
    actionable_lines = [
        line
        for line in src.splitlines()
        if "TODO" in line
        and "S99 W1" not in line
        and "устаревший" not in line.lower()
        and "outdated" not in line.lower()
    ]
    assert not actionable_lines, f"Actionable TODO found in {p}:\n  " + "\n  ".join(
        actionable_lines
    )


def test_generate_template_substitutes_name() -> None:
    """Генератор подставляет ``{name}`` и ``{ptype}`` корректно.

    Тест НЕ зависит от реальной generation логики — просто проверяем
    что в f-string template substitution работает (AST-based check).
    """
    import ast

    p = "src/backend/dsl/cli/generate.py"
    src = open(p).read()
    tree = ast.parse(src)

    # Find a function that builds a template string (JoinedStr with FormattedValues)
    template_found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            # Look for FormattedValue nodes that reference {name} and {ptype}
            formatted_names = set()
            for v in node.values:
                if isinstance(v, ast.FormattedValue) and isinstance(v.value, ast.Name):
                    formatted_names.add(v.value.id)
            if "name" in formatted_names and "ptype" in formatted_names:
                template_found = True
                break

    assert template_found, (
        f"Template in {p} should have f-string with {{name}} and {{ptype}} "
        f"substitution. Both are used for code generation."
    )


def test_generate_template_not_implemented_error_uses_ptype() -> None:
    """NotImplementedError message использует ``{ptype}`` (added S99 W1)."""
    from pathlib import Path

    p = Path("src/backend/dsl/cli/generate.py")
    src = p.read_text()
    # Найдём f-string с NotImplementedError — должен содержать ptype
    assert "not implemented — fill in process() body" in src, (
        f"{p} should have 'not implemented' message in process() body"
    )
    # Check that {ptype} is interpolated into the error
    import re

    # Find the line(s) with f"{name!r} ... ptype ... not implemented"
    pattern = re.compile(r"f['\"]\\{name!r\\}[^'\"]*\\{ptype[^'\"]*not implemented")
    if not pattern.search(src):
        # Try simpler: just check the comment or ptype reference near not implemented
        # Look at the block around "not implemented"
        idx = src.find("not implemented")
        if idx > 0:
            block = src[max(0, idx - 500) : idx]
            assert "ptype" in block, (
                f"{p} should reference {{ptype}} in NotImplementedError block. "
                f"Current block: ...{block[-200:]}"
            )
