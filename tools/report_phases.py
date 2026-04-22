#!/usr/bin/env python3
"""Короткий CLI-отчёт по фазам.

Использование::

    python3 tools/report_phases.py
    python3 tools/report_phases.py --only in-progress
    python3 tools/report_phases.py --only done
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
STATUS = ROOT / "docs" / "adr" / "PHASE_STATUS.yml"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", choices=["planned", "in-progress", "done"])
    args = parser.parse_args()

    if not STATUS.exists():
        print("PHASE_STATUS.yml not found", file=sys.stderr)
        return 1
    data = yaml.safe_load(STATUS.read_text(encoding="utf-8")) or {}
    phases = data.get("phases") or {}
    by_status: dict[str, int] = {"planned": 0, "in-progress": 0, "done": 0}
    for pid, phase in phases.items():
        st = phase.get("status", "planned")
        by_status[st] = by_status.get(st, 0) + 1
        if args.only and st != args.only:
            continue
        adr = ",".join(phase.get("adr") or []) or "—"
        print(f"{pid:>3} [{st:<12}] {phase.get('title', '?')}  (ADR: {adr})")
    print()
    print(
        f"TOTAL: {len(phases)}  planned={by_status['planned']}  "
        f"in-progress={by_status['in-progress']}  done={by_status['done']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
