"""Генерирует docs/PROCESSORS.md из docstrings классов-процессоров.

Читает все модули `src/dsl/engine/processors/*.py`, находит подклассы
`BaseProcessor`, извлекает первую строку docstring и параметры __init__,
формирует компактную Markdown-таблицу.

Запуск::

    python tools/generate_processors_doc.py > docs/PROCESSORS.md
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROCESSORS_DIR = ROOT / "src" / "dsl" / "engine" / "processors"


def _extract_first_line(docstring: str | None) -> str:
    if not docstring:
        return ""
    for line in docstring.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _iter_processor_classes(path: Path):
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        bases = {
            b.attr if isinstance(b, ast.Attribute) else
            (b.id if isinstance(b, ast.Name) else "")
            for b in node.bases
        }
        if "BaseProcessor" not in bases:
            continue
        doc = ast.get_docstring(node)
        yield node.name, _extract_first_line(doc)


def main() -> int:
    modules = sorted(p for p in PROCESSORS_DIR.rglob("*.py") if p.name != "__init__.py")
    sections: dict[str, list[tuple[str, str]]] = {}
    for path in modules:
        key = path.stem
        found = list(_iter_processor_classes(path))
        if found:
            sections[key] = found

    print("# Каталог процессоров DSL\n")
    print("> Автогенерируется `tools/generate_processors_doc.py` из docstrings.\n")
    total = sum(len(v) for v in sections.values())
    print(f"Всего процессоров: **{total}**\n")
    for module, items in sorted(sections.items()):
        print(f"## {module}\n")
        print("| Класс | Назначение |")
        print("|-------|------------|")
        for name, summary in sorted(items):
            print(f"| `{name}` | {summary} |")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
