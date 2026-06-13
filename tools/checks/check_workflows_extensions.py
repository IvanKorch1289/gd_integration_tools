"""Gate: domain-workflows должны жить только в extensions/ (Sprint 10 K3).

Запрещает любые импорты из ``src.backend.workflows.{orders_saga,
payments_saga,orders_dsl}``: shims удалены в Sprint 10. Все callsites
должны идти прямо в ``extensions.core_entities.orders.workflows.*``
или ``extensions.credit_pipeline.workflows.*``.

Запуск:

.. code-block:: bash

    python tools/checks/check_workflows_extensions.py
    # exit 0 — нет нарушений
    # exit 1 — найден импорт мимо extensions/
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

IMPORT_RE = re.compile(
    r"^\s*(?:from|import)\s+src\.backend\.workflows\."
    r"(orders_saga|payments_saga|orders_dsl)\b",
    re.MULTILINE,
)


def find_violations(root: Path) -> list[tuple[str, int, str]]:
    """Возвращает list (relpath, line_number, matched_module)."""
    violations: list[tuple[str, int, str]] = []
    for py_file in root.rglob("*.py"):
        rel = str(py_file.relative_to(root))
        if "/__pycache__/" in rel or "/.venv/" in rel or "/.git/" in rel:
            continue
        try:
            text = py_file.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for match in IMPORT_RE.finditer(text):
            line_no = text[: match.start()].count("\n") + 1
            violations.append((rel, line_no, match.group(1)))
    return violations


def main() -> int:
    """Entry point."""
    violations = find_violations(ROOT)
    if not violations:
        print("OK: no legacy-workflow imports detected")
        return 0
    print(f"FOUND {len(violations)} legacy-workflow imports:")
    for rel, line_no, module in violations:
        print(f"  {rel}:{line_no} → src.backend.workflows.{module}")
    print()
    print("Shims удалены в S10. Импортируйте из extensions/ напрямую.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
