#!/usr/bin/env python3
"""Pre-commit commit-msg hook.

Если фаза из commit-message требует ADR (таблица из ``PHASE_STATUS.yml``,
поле ``adr``), в теле коммита должна быть ссылка вида ``ADR-NNN`` хотя бы
на один из ожидаемых ADR. Иначе коммит отклоняется.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
STATUS = ROOT / "docs" / "adr" / "PHASE_STATUS.yml"

PHASE_RE = re.compile(r"^\[phase:([A-Z]+\d+[a-z]?)\]")
ADR_RE = re.compile(r"\bADR-(\d{3})\b")


def main() -> int:
    if len(sys.argv) < 2 or not STATUS.exists():
        return 0
    msg = Path(sys.argv[1]).read_text(encoding="utf-8")
    first_line = msg.splitlines()[0] if msg else ""
    m = PHASE_RE.match(first_line)
    if not m:
        return 0
    phase_id = m.group(1)
    data = yaml.safe_load(STATUS.read_text(encoding="utf-8")) or {}
    phase = (data.get("phases") or {}).get(phase_id)
    if not phase:
        return 0
    required = phase.get("adr") or []
    if not required:
        return 0
    found = {f"ADR-{n}" for n in ADR_RE.findall(msg)}
    missing = [a for a in required if a not in found]
    if missing:
        print(
            f"ERROR: commit для фазы {phase_id} должен упоминать в теле "
            f"следующие ADR: {', '.join(missing)}.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
