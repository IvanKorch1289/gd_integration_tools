#!/usr/bin/env python3
"""Pre-commit hook: HARD-BLOCK на написание тестов.

Заказчик явно исключил тестовую инфраструктуру из плана реализации.
Любая попытка добавить ``tests/``, ``test_*.py``, ``*_test.py``, ``conftest.py``
или импортировать ``pytest``/``pytest_asyncio``/``hypothesis``/``mutmut``/
``testcontainers``/``pact`` — ОТКЛОНЯЕТСЯ на уровне pre-commit и CI-job
``no-tests-gate``.

Вызов: ``check_no_tests.py <staged files...>``.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

BAD_PATHS = (
    re.compile(r"(^|/)tests(/|$)"),
    re.compile(r"(^|/)test_[^/]+\.py$"),
    re.compile(r"(^|/)[^/]+_test\.py$"),
    re.compile(r"(^|/)conftest\.py$"),
)

BAD_IMPORTS = re.compile(
    r"^\s*(?:from|import)\s+"
    r"(pytest|pytest_asyncio|hypothesis|mutmut|testcontainers|pact(?:_python)?|nose|unittest)"
    r"(?:\s|\.|$)",
    re.MULTILINE,
)


def main() -> int:
    files = [Path(p) for p in sys.argv[1:]]
    errors: list[str] = []
    for f in files:
        rel = str(f)
        for pat in BAD_PATHS:
            if pat.search(rel):
                errors.append(f"{rel}: путь запрещён политикой 'no tests'")
                break
        if f.suffix == ".py" and f.exists():
            try:
                text = f.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if BAD_IMPORTS.search(text):
                errors.append(f"{rel}: содержит запрещённый импорт тестового фреймворка")
    if errors:
        print("ERROR: политика 'no tests' нарушена:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        print(
            "\nЗаказчик явно исключил написание тестов. Если вы уверены, "
            "что нужен временный байпас — запросите отдельное согласование "
            "и оформите явный ADR.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
