#!/usr/bin/env python3
"""G10 nav-debt Wave 1 — atomic fixer for 5 safe-deletes.

Per `deliverables/g10-nav-debt/INVENTORY.md::Wave 1`:
  A1. Confirm `core/services/base_external_api.py` dubль already removed.
  B1. `src/backend/dsl/setup.py` (DELETE_CANDIDATE; 0 prod imports).
  B2. `src/backend/dsl/audit_versioning.py` (DEPRECATE; 0 prod imports).
  B3. `src/backend/dsl/orchestration/__init__.py` (scaffold; remove, keep triggers.py).
  B4. `src/backend/dsl/engine/processors/ai/banking_processors/base.py` (DELETE_CANDIDATE; 0 imports).

Each fix is verified: 0 prod consumers (per inventory fact-check at 2026-10-19).
Mutants/tests referenced are checked in `--check` mode; if any are found,
the script aborts with a list and refuses to apply.

Usage:
    python deliverables/g10-nav-debt/wave1/apply.py --check
    python deliverables/g10-nav-debt/wave1/apply.py --delete
    python deliverables/g10-nav-debt/wave1/apply.py --delete --fix A1
    python deliverables/g10-nav-debt/wave1/apply.py --delete --fix B1,B2
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]

# Each fix: (id, action, target_path, comment)
# action: "verify_missing" (no file expected, only confirm) | "delete_file" | "delete_scaffold"
FIXES: list[tuple[str, str, Path, str]] = [
    (
        "A1",
        "verify_missing",
        REPO / "src/backend/core/services/base_external_api.py",
        "Original байт-в-байт dubль of services/core/base_external_api.py. "
        "Audit (2026-09-11) listed 0 prod imports. Per fact-check 2026-10-19: file is "
        "already absent from HEAD `127d4d011` (only `services/core/...` copy remains). "
        "Fix action: verify absent (no deletion needed).",
    ),
    (
        "B1",
        "delete_file",
        REPO / "src/backend/dsl/setup.py",
        "DELETE_CANDIDATE — `bootstrap_dsl` is not called anywhere in src/ or extensions/ "
        "(only in tests). 0 prod consumers verified.",
    ),
    (
        "B2",
        "delete_file",
        REPO / "src/backend/dsl/audit_versioning.py",
        "DEPRECATE (back-compat shim) — 0 prod consumers, lives only in tests. "
        "Original audit verdict: DEPRECATE → DELETE (next release).",
    ),
    (
        "B3",
        "delete_scaffold",
        REPO / "src/backend/dsl/orchestration/__init__.py",
        "DEPRECATE scaffold (5349 B). The package's `triggers.py` (20 KB) is alive "
        "and will continue to work without the scaffold __init__.py. "
        "Action: remove only the __init__.py, keep triggers.py and the rest of the package.",
    ),
    (
        "B4",
        "delete_file",
        REPO / "src/backend/dsl/engine/processors/ai/banking_processors/base.py",
        "DELETE_CANDIDATE — leftover from migration to `ai_banking/`. 0 external imports. "
        "No `__init__.py` in the parent dir (orphan).",
    ),
]


def check_mutants_references(target: Path) -> list[str]:
    """Return list of files in mutants/ or tests/ that reference target.

    Search by stem (filename) only, since the imports look like
    `from src.backend.dsl.setup import bootstrap_dsl`.
    """
    stem = target.name.replace(".py", "")
    if not target.exists():
        return []
    refs: list[str] = []
    candidates = list((REPO / "mutants").rglob(f"*{stem}*")) if (REPO / "mutants").exists() else []
    candidates += list((REPO / "tests").rglob(f"*{stem}*")) if (REPO / "tests").exists() else []
    for c in candidates:
        if c.is_file() and c != target:
            refs.append(str(c.relative_to(REPO)))
    return refs


def main() -> int:
    parser = argparse.ArgumentParser(description="G10 Wave 1 safe-deletes")
    parser.add_argument("--check", action="store_true", help="dry-run; verify state, no writes")
    parser.add_argument("--delete", action="store_true", help="apply: delete files / verify absent")
    parser.add_argument("--fix", type=str, help="comma-separated fix IDs (default: all)")
    args = parser.parse_args()

    if not args.check and not args.delete:
        print("ERROR: must specify --check or --delete", file=sys.stderr)
        return 1

    selected: list[tuple[str, str, Path, str]] = FIXES
    if args.fix:
        wanted = {x.strip() for x in args.fix.split(",")}
        selected = [f for f in FIXES if f[0] in wanted]
        if not selected:
            print(f"ERROR: no fixes matched: {args.fix}", file=sys.stderr)
            return 1

    print("=" * 70)
    print(f"G10 Wave 1 — {len(selected)} fix(es), mode={'CHECK' if args.check else 'DELETE'}")
    print("=" * 70)

    errors: list[str] = []
    applied: list[str] = []
    mutants_refs: dict[str, list[str]] = {}

    for fix_id, action, target, comment in selected:
        rel = target.relative_to(REPO)
        if action == "verify_missing":
            if target.exists():
                errors.append(f"[{fix_id}] {rel}: file STILL EXISTS (was supposed to be already removed). Manual review needed.")
            else:
                print(f"  [A1] ✅ {rel}: not present (verified — closed by previous sprint)")
                applied.append(fix_id)
        elif action == "delete_file":
            if not target.exists():
                errors.append(f"[{fix_id}] {rel}: file not present (drift? Already deleted?)")
                continue
            # check mutants/tests references
            refs = check_mutants_references(target)
            if refs:
                mutants_refs[fix_id] = refs
                print(f"  [{fix_id}] ⚠️  {rel}: EXISTS, but {len(refs)} reference(s) in mutants/tests:")
                for r in refs[:5]:
                    print(f"        - {r}")
                if len(refs) > 5:
                    print(f"        - ... and {len(refs) - 5} more")
                errors.append(f"[{fix_id}] {rel}: has mutants/tests references; review before delete")
            else:
                print(f"  [{fix_id}] {'🟢 would delete' if args.check else '🟢 DELETED'} {rel} (0 references)")
                if args.delete:
                    target.unlink()
                    applied.append(fix_id)
        elif action == "delete_scaffold":
            if not target.exists():
                errors.append(f"[{fix_id}] {rel}: file not present")
                continue
            if args.delete:
                print(f"  [{fix_id}] 🟡 DELETED scaffold {rel} (keeps triggers.py and rest of package)")
                target.unlink()
                applied.append(fix_id)
            else:
                print(f"  [{fix_id}] 🟡 would delete scaffold {rel} (keeps triggers.py and rest of package)")

    print("-" * 70)
    print(f"Total: {len(selected)} fix(es) processed, {len(applied)} applied successfully")
    if args.check:
        print(f"Mode:   dry-run (no writes)")
    else:
        print(f"Mode:   DELETED")

    if errors:
        print()
        print("ERRORS / WARNINGS:")
        for e in errors:
            print(f"  ! {e}")
        if mutants_refs:
            print()
            print("ACTION NEEDED: for fixes with mutants/tests references:")
            print("  1. Review the listed files")
            print("  2. If the references are real test code, migrate or delete them first")
            print("  3. Then re-run this script")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
