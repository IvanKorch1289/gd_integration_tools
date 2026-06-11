"""CI-gate: анализ использования feature-flags.

Ищет:
- feature flags, определённые в ``src/backend/core/config/features/``;
- их использование в ``src/backend/`` и ``extensions/``;
- flags, которые определены, но нигде не используются (potential dead flags).

Exit codes:
    0 — анализ завершён, dead flags не найдены (или warn-only).
    1 — strict + найдены dead flags.

Usage::

    python tools/checks/check_feature_flag_usage.py
    python tools/checks/check_feature_flag_usage.py --strict
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path


def _collect_flags(root: Path) -> set[str]:
    flags: set[str] = set()
    for f in root.rglob("*.py"):
        if f.name == "__init__.py":
            continue
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                n = node.target.id
                if not n.startswith("_") and n != "model_config":
                    flags.add(n)
            elif isinstance(node, ast.Assign):
                for tgt in node.targets:
                    if isinstance(tgt, ast.Name):
                        n = tgt.id
                        if not n.startswith("_") and n != "model_config":
                            flags.add(n)
    return flags


def _find_unused(flags: set[str], search_roots: list[Path]) -> set[str]:
    used: set[str] = set()
    for root in search_roots:
        for f in root.rglob("*.py"):
            try:
                text = f.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:  # noqa: S112  # dev-tool: skip unreadable/binary files
                print(
                    f"[check_feature_flag_usage] skip {f}: {type(exc).__name__}: {exc}",
                    file=__import__("sys").stderr,
                )
                continue
            for flag in flags:
                if flag in text:
                    used.add(flag)
    return flags - used


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 при dead flags (default: warn-only).",
    )
    args = parser.parse_args()

    features_dir = Path("src/backend/core/config/features")
    flags = _collect_flags(features_dir)
    print(f"Total feature flags defined: {len(flags)}")

    unused = _find_unused(flags, [Path("src/backend"), Path("extensions")])
    if not unused:
        print("✓ All feature flags are referenced in code.")
        return 0

    print(f"⚠ Dead feature flags ({len(unused)}):")
    for flag in sorted(unused):
        print(f"  - {flag}")

    if args.strict:
        return 1
    print("(warn-only mode)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
