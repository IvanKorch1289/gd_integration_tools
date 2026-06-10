"""S48 W4 AST audit — find suspicious except: pass patterns.

Distinguishes:
- CRITICAL: bare except (catches SystemExit, KeyboardInterrupt, etc.)
- MEDIUM: except Exception: pass (silent failure, may hide bugs)
- OK: specific exception, probably intentional

Usage:
    uv run python tools/audit_silent_excepts.py [--root src/backend] [--json]

Exit code:
- 0: no CRITICAL or MEDIUM findings
- 1: at least one CRITICAL or MEDIUM finding
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import sys
from collections import Counter


def audit(root: str) -> list[dict[str, object]]:
    """Find suspicious except: pass patterns in Python source files."""
    findings: list[dict[str, object]] = []
    for dirpath, dirs, files in os.walk(root):
        if "__pycache__" in dirpath:
            continue
        for f in files:
            if not f.endswith(".py"):
                continue
            full = os.path.join(dirpath, f)
            try:
                src = open(full).read()
                tree = ast.parse(src)
            except (SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.ExceptHandler):
                    continue
                if not node.body or len(node.body) != 1:
                    continue
                body_stmt = node.body[0]
                if not isinstance(body_stmt, ast.Pass):
                    continue
                type_str = ast.unparse(node.type) if node.type else "<bare>"
                if node.type is None:
                    severity = "CRITICAL"
                    reason = "bare except (catches SystemExit, KeyboardInterrupt)"
                else:
                    if "Exception" in type_str and "," not in type_str:
                        severity = "MEDIUM"
                        reason = "except Exception: pass (silent failure, may hide bugs)"
                    else:
                        # Specific exception — likely intentional.
                        continue
                findings.append(
                    {
                        "file": full,
                        "line": node.lineno,
                        "type": type_str,
                        "severity": severity,
                        "reason": reason,
                    }
                )
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit silent except: pass patterns in Python source."
    )
    parser.add_argument(
        "--root",
        default="src/backend",
        help="Root directory to scan (default: src/backend)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output JSON instead of human-readable text",
    )
    args = parser.parse_args()

    findings = audit(args.root)
    by_severity = Counter(f["severity"] for f in findings)

    if args.json:
        print(
            json.dumps(
                {
                    "total": len(findings),
                    "by_severity": dict(by_severity),
                    "findings": findings,
                },
                indent=2,
            )
        )
    else:
        print(f"Suspicious findings: {len(findings)}")
        print(f"By severity: {dict(by_severity)}")
        print()
        critical = [f for f in findings if f["severity"] == "CRITICAL"]
        if critical:
            print("CRITICAL (bare except: pass):")
            for f in critical[:20]:
                print(f"  {f['file']}:{f['line']}  except {f['type']}: pass")
            print()
        medium = [f for f in findings if f["severity"] == "MEDIUM"]
        print(f"MEDIUM count: {len(medium)}")
        if medium:
            print("MEDIUM (except Exception: pass) — sample 10:")
            for f in medium[:10]:
                print(f"  {f['file']}:{f['line']}  except {f['type']}: pass")
            print(f"  ... and {len(medium) - 10} more")

    return 0 if by_severity.get("CRITICAL", 0) == 0 and by_severity.get("MEDIUM", 0) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
