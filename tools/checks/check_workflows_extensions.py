"""Gate: domain-workflows должны жить только в extensions/ (Sprint 9 K5 W4).

Запрещает NEW импорты из ``src.backend.workflows.{orders_saga,payments_saga,
orders_dsl}`` — это deprecation shims на один спринт (S9 → S10) для
backwards-compat. Новые callsites должны идти прямо в
``extensions.core_entities.orders.workflows.*`` или
``extensions.credit_pipeline.workflows.*``.

Whitelist legitimate-importers (shims самой migration и tests):

* ``src/backend/workflows/{orders_saga,payments_saga,orders_dsl}.py`` —
  shim-файлы (содержат re-export, разрешены).
* ``src/backend/plugins/composition/workflow_setup.py`` — legacy composition root;
  будет рефакторен в S10.
* ``tests/unit/workflows/*`` — legacy unit-тесты; обновятся в S10.

Запуск:

.. code-block:: bash

    python tools/checks/check_workflows_extensions.py
    # exit 0 — нет нарушений
    # exit 1 — найден новый импорт мимо whitelist
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Регулярка для импорта старых модулей
IMPORT_RE = re.compile(
    r"^\s*(?:from|import)\s+src\.backend\.workflows\."
    r"(orders_saga|payments_saga|orders_dsl)\b",
    re.MULTILINE,
)

WHITELIST = {
    "src/backend/workflows/orders_saga.py",
    "src/backend/workflows/payments_saga.py",
    "src/backend/workflows/orders_dsl.py",
    "src/backend/plugins/composition/workflow_setup.py",
    "tests/unit/workflows/test_payments_saga.py",
    "tests/unit/workflows/test_orders_saga.py",
    "tests/unit/dsl/workflow/test_yaml_io.py",
}


def find_violations(root: Path) -> list[tuple[str, int, str]]:
    """Возвращает list (relpath, line_number, matched_module)."""
    violations: list[tuple[str, int, str]] = []
    for py_file in root.rglob("*.py"):
        rel = str(py_file.relative_to(root))
        if rel in WHITELIST:
            continue
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
        print("OK: no new legacy-workflow imports detected")
        return 0
    print(f"FOUND {len(violations)} new legacy-workflow imports:")
    for rel, line_no, module in violations:
        print(f"  {rel}:{line_no} → src.backend.workflows.{module}")
    print()
    print("Migrate to extensions/* (see docs/migration/* for guide).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
