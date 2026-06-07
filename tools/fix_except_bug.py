"""S60 W3 codemod: fix 'except A, B:' (semantic bug) → 'except (A, B):'.

Background: in Python 3.x, ``except A, B:`` is NOT a syntax error.
It means "catch A, bind to name B" — NOT "catch A or B".
When the developer intended multiple types, they forgot parens.

Examples (all REAL bugs found in src/):
- ``except TypeError, ValueError:``        → catches ONLY TypeError
- ``except ImportError, AttributeError:`` → catches ONLY ImportError
- ``except asyncio.CancelledError, Exception:`` → catches ONLY CancelledError

The fix: wrap the comma-separated list in parens:
- ``except (TypeError, ValueError):`` — catches both
- ``except (ImportError, AttributeError):`` — catches both

Caveat: ``except X, e:`` (single-letter alias) is the LEGITIMATE use of
this syntax. The codemod skips those where the second arg is a short
identifier (likely an alias variable).

Idempotent: detects already-parenthesized tuples and skips.
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

# Match `except A, B, C:` (NOT in parens) — at module/class/function level
# Negative lookbehind for `(` to skip already-parenthesized tuples
RE_EXCEPT_COMMA = re.compile(
    r"^(?P<indent>[ \t]*)except (?P<types>(?:\s*[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*\s*,\s*)+[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\s*(?P<rest>as\s+[A-Za-z_][A-Za-z0-9_]*)?\s*:\s*$",
    re.MULTILINE,
)

# Heuristic: if the SECOND name (after the first comma) is a short identifier
# (1-3 chars, lowercase), it's likely an alias var, not a type.
# Real exceptions have CamelCase or dotted names like json.JSONDecodeError.
ALIAS_PATTERN = re.compile(r"^[a-z_][a-z0-9_]{0,2}$")


def is_likely_alias(types_str: str) -> bool:
    """True if the LAST name in the comma-list looks like an alias variable."""
    parts = [p.strip() for p in types_str.split(",")]
    if len(parts) < 2:
        return False
    last = parts[-1]
    # CamelCase or dotted: clearly a type
    if "." in last or last[:1].isupper():
        return False
    # Single letter or 2-3 char lowercase: alias
    if ALIAS_PATTERN.match(last):
        return True
    return False


def has_as_alias(types_str: str, rest: str) -> bool:
    """True if the line has explicit 'as name' (definitely alias, skip)."""
    return bool(rest and rest.strip().startswith("as "))


def process_file(path: Path, dry_run: bool = False) -> tuple[bool, list[str]]:
    src = path.read_text(encoding="utf-8")
    matches = list(RE_EXCEPT_COMMA.finditer(src))
    if not matches:
        return False, []

    changes: list[str] = []
    new_src = src
    # Process in reverse to preserve offsets
    for m in reversed(matches):
        types_str = m.group("types")
        rest = m.group("rest") or ""
        if has_as_alias(types_str, rest):
            continue
        if is_likely_alias(types_str):
            continue
        indent = m.group("indent")
        # Wrap in parens
        replacement = f"{indent}except ({types_str}){rest}:"
        new_src = new_src[: m.start()] + replacement + new_src[m.end() :]
        changes.append(f"{path}:{src[: m.start()].count(chr(10)) + 1}: {types_str}")

    if new_src == src:
        return False, []

    if not dry_run:
        path.write_text(new_src, encoding="utf-8")
    return True, changes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", default=["src/"])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    files: list[Path] = []
    for p in args.paths:
        path = Path(p)
        if path.is_file():
            files.append(path)
        else:
            files.extend(path.rglob("*.py"))

    changed_count = 0
    skipped_count = 0
    total_changes = 0

    for f in sorted(files):
        if "__pycache__" in f.parts or ".venv" in f.parts or "node_modules" in f.parts:
            continue
        try:
            changed, changes = process_file(f, dry_run=args.dry_run)
            if changed:
                changed_count += 1
                total_changes += len(changes)
                for c in changes:
                    print(f"  CHANGE: {c}")
            else:
                skipped_count += 1
        except Exception as e:
            print(f"  ERROR: {f}: {e}", file=sys.stderr)

    print(f"\nSummary: {changed_count} files changed, {skipped_count} skipped, {total_changes} total fixes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
