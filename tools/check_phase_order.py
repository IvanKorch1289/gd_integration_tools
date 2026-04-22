#!/usr/bin/env python3
"""Pre-commit hook: запрет закрытия фазы с невыполненными зависимостями.

Читает ``docs/adr/PHASE_STATUS.yml``. Для каждой фазы со статусом ``done``
проверяет, что все фазы из ``depends_on`` тоже имеют статус ``done``.
Иначе — ошибка и отказ в коммите.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
STATUS = ROOT / "docs" / "adr" / "PHASE_STATUS.yml"


def main() -> int:
    if not STATUS.exists():
        return 0
    data = yaml.safe_load(STATUS.read_text(encoding="utf-8")) or {}
    phases = data.get("phases") or {}
    errors: list[str] = []
    for pid, phase in phases.items():
        if phase.get("status") != "done":
            continue
        for dep in phase.get("depends_on") or []:
            dep_status = (phases.get(dep) or {}).get("status")
            if dep_status != "done":
                errors.append(f"{pid} закрыта, но зависимость {dep} в статусе '{dep_status}'")
    if errors:
        print("ERROR: нарушен порядок закрытия фаз:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
