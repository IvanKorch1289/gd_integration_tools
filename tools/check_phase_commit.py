#!/usr/bin/env python3
"""Pre-commit commit-msg hook.

Блокирует коммит, если commit-message не начинается с префикса ``[phase:<ID>]``.
ID должен существовать в ``docs/adr/PHASE_STATUS.yml``.

Исключения (проходят без префикса): merge-коммиты, revert, initial bootstrap.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
STATUS = ROOT / "docs" / "adr" / "PHASE_STATUS.yml"

PHASE_RE = re.compile(r"^\[phase:([A-Z]\d+[a-z]?)\] .+")
BYPASS_RE = re.compile(r"^(Merge |Revert )")


def main() -> int:
    if len(sys.argv) < 2:
        return 0
    msg_path = Path(sys.argv[1])
    first_line = msg_path.read_text(encoding="utf-8").splitlines()[0] if msg_path.exists() else ""
    if BYPASS_RE.match(first_line):
        return 0
    m = PHASE_RE.match(first_line)
    if not m:
        print(
            "ERROR: commit-message должен начинаться с префикса [phase:<ID>] "
            "(например, '[phase:A1] baseline inventory'). "
            "Полный формат см. docs/phases/PHASE_A1.md.",
            file=sys.stderr,
        )
        return 1
    phase_id = m.group(1)
    if STATUS.exists():
        data = yaml.safe_load(STATUS.read_text(encoding="utf-8")) or {}
        phases = (data or {}).get("phases", {})
        if phase_id not in phases:
            print(
                f"ERROR: фаза {phase_id} не объявлена в docs/adr/PHASE_STATUS.yml",
                file=sys.stderr,
            )
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
