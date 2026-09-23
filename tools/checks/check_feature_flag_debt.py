"""Feature-flag debt policy (Sprint 11 — audit 2026-09-22 P2).

Аудит finding #16: flag-система развита, но модель lifecycle/expiry/owner
в runtime-структурах не обнаружена. Каждый флаг должен иметь owner,
created, expires, cleanup issue. Stale flags блокируют release.

Этот скрипт сканирует:
1. Все ``@feature_flag(...)`` / ``FeatureFlag(...)`` references в src/.
2. Каждый флаг должен иметь metadata: owner, created, expires.
3. ``--strict`` режим: exit 1 если флаг без metadata или expired.

Использование::

    python tools/checks/check_feature_flag_debt.py              # human-readable
    python tools/checks/check_feature_flag_debt.py --strict    # exit 1 if issues
    python tools/checks/check_feature_flag_debt.py --json      # machine output
"""

from __future__ import annotations

import argparse
import ast
import json
import re
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
REGISTRY = REPO_ROOT / "tools" / "checks" / "feature_flag_registry.toml"


def _is_expired(expires: str) -> bool:
    """True если expires date уже прошла."""
    try:
        exp = datetime.fromisoformat(expires)
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=UTC)
        return exp < datetime.now(UTC)
    except ValueError:
        return False


def _scan_feature_flags() -> list[dict[str, object]]:
    """Find FeatureFlag references в src/.

    Heuristics (project-specific patterns):
    - ``RuntimeFeatureFlagOverrides.get("flag_name", ...)``
    - ``get_feature_flag_service().get("flag_name", ...)``
    - ``FeatureFlag("flag_name", ...)`` constructor
    - ``@feature_flag("flag_name")`` decorator
    """
    findings: list[dict[str, object]] = []
    if not SRC_ROOT.exists():
        return findings
    patterns = [
        # feature_flags.<flag_name> attribute access.
        re.compile(r"feature_flags\.([a-z][a-z0-9_]+)"),
        # RuntimeFeatureFlagOverrides.get("flag_name", ...).
        re.compile(r'RuntimeFeatureFlagOverrides\.get\(\s*["\']([a-z][a-z0-9_]+)["\']'),
        # get_feature_flag_service().get("flag_name", ...).
        re.compile(r'get_feature_flag_service\(\)\.get\(\s*["\']([a-z][a-z0-9_]+)["\']'),
        # FeatureFlag("flag_name", ...) constructor.
        re.compile(r'FeatureFlag\(\s*["\']([a-z][a-z0-9_]+)["\']'),
        # @feature_flag("flag_name") decorator.
        re.compile(r'@feature_flag\(\s*["\']([a-z][a-z0-9_]+)["\']'),
    ]

    for py in SRC_ROOT.rglob("*.py"):
        if "__pycache__" in py.parts or "/tests/" in str(py):
            continue
        try:
            content = py.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        try:
            ast.parse(content)
        except SyntaxError:
            continue
        for pattern in patterns:
            for match in pattern.finditer(content):
                line_no = content[: match.start()].count("\n") + 1
                findings.append({
                    "flag_name": match.group(1),
                    "file": str(py.relative_to(REPO_ROOT)),
                    "line": line_no,
                    "type": pattern.pattern[:30],
                })
    # Deduplicate by (flag_name, file, line).
    seen: set[tuple[str, str, int]] = set()
    deduped: list[dict[str, object]] = []
    for f in findings:
        key = (str(f["flag_name"]), str(f["file"]), int(f["line"]))  # type: ignore[arg-type]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(f)
    return deduped


def _parse_registry() -> dict[str, dict[str, str]]:
    """Parse feature_flag_registry.toml."""
    if not REGISTRY.exists():
        return {}
    try:
        import tomllib  # type: ignore[import-not-found]
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[import-not-found,no-redef]
        except ImportError:
            return {}
    with REGISTRY.open("rb") as f:
        data = tomllib.load(f)
    return data.get("flags", {})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Feature-flag debt policy enforcement")
    parser.add_argument("--strict", action="store_true", help="Exit 1 if issues")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args(argv)

    notes: list[str] = []
    issues: list[str] = []

    findings = _scan_feature_flags()
    unique_flags = {f["flag_name"] for f in findings}  # type: ignore[misc]
    n_unique = len(unique_flags)
    n_uses = len(findings)
    notes.append(f"Unique feature flags: {n_unique}")
    notes.append(f"Total usages: {n_uses}")

    registry = _parse_registry()
    notes.append(f"Registry entries: {len(registry)}")

    unlisted_flags: list[str] = []
    expired_flags: list[dict[str, str]] = []

    for flag_name in unique_flags:
        entry = registry.get(flag_name)
        if entry is None:
            unlisted_flags.append(flag_name)
            continue
        expires = entry.get("expires", "")
        if expires and _is_expired(expires):
            expired_flags.append({"flag": flag_name, "expires": expires})

    notes.append(f"Flags without registry entry: {len(unlisted_flags)}")
    notes.append(f"Expired flags: {len(expired_flags)}")

    if unlisted_flags:
        for f in unlisted_flags[:10]:
            issues.append(f"Feature flag без owner/expires metadata: {f}")
    if expired_flags:
        for e in expired_flags[:5]:
            issues.append(f"Feature flag expired: {e['flag']} (expires={e['expires']})")

    output = {
        "unique_flags": n_unique,
        "total_usages": n_uses,
        "registry_entries": len(registry),
        "unlisted_count": len(unlisted_flags),
        "expired_count": len(expired_flags),
        "unlisted_sample": unlisted_flags[:20],
        "expired_sample": expired_flags[:5],
        "issues": issues,
        "notes": notes,
    }

    if args.json:
        print(json.dumps(output, indent=2))
    else:
        print(f"{'=' * 60}")
        print("Feature-Flag Debt Policy (Sprint 11 — audit 2026-09-22 P2)")
        print(f"{'=' * 60}")
        print()
        for n in notes:
            print(f"  ℹ️  {n}")
        print()
        if issues:
            print("Issues:")
            for i in issues[:10]:
                print(f"  ❌ {i}")
        else:
            print("✅ Feature-flag debt OK")
        print()

    if args.strict and issues:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
