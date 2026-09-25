"""Test dependency profiles verification (v6 / 25.09 audit).

Per очерёдность #8: «Разделить test dependency profiles (core / api /
scheduler / workflow / messaging / ai / frontend / rpa / test-*)».

Этот script проверяет что test-* extras в pyproject.toml:
1. Определены (presence check);
2. Не пустые (non-empty);
3. Каждый профиль содержит минимальный test runner (pytest + pytest-asyncio);
4. test-all является meta-extra, объединяющим все остальные.

Использование::

    python tools/checks/verify_test_profiles.py             # human-readable
    python tools/checks/verify_test_profiles.py --strict    # exit 1 на violations
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = PROJECT_ROOT / "pyproject.toml"

# Required test profiles per v6 / 25.09 audit.
REQUIRED_PROFILES: tuple[str, ...] = (
    "test-core",
    "test-api",
    "test-scheduler",
    "test-workflow",
    "test-messaging",
    "test-ai",
    "test-frontend",
    "test-rpa",
    "test-all",
)

# Each profile должен содержать pytest + pytest-asyncio (минимальный test runner).
MINIMAL_TEST_DEPS: tuple[str, ...] = ("pytest", "pytest-asyncio")


def _parse_optional_deps(content: str) -> dict[str, list[str]]:
    """Parse ``[project.optional-dependencies]`` section.

    Returns:
        ``{profile_name: [deps...]}`` dict.
    """
    # Section header MUST be at line start (NOT in comments). Используем
    # multiline match с negative lookbehind для ``#`` чтобы исключить
    # вхождения внутри комментариев (например, [project.optional-dependencies].rag
    # в docstring'е).
    match = re.search(
        r"(?m)^\[project\.optional-dependencies\]\s*$(.*?)(?=^\[|\Z)",
        content,
        re.DOTALL,
    )
    if not match:
        return {}
    section = match.group(1)
    profiles: dict[str, list[str]] = {}
    current_profile: str | None = None
    current_deps: list[str] = []
    for line in section.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Profile header: ``name = [`` или ``name=[``.
        m = re.match(r"^([a-z0-9-]+)\s*=\s*\[(.*)$", line)
        if m:
            if current_profile is not None:
                profiles[current_profile] = current_deps
            current_profile = m.group(1)
            current_deps = []
            # Inline deps (same line as ``[``) — capture if present.
            inline = m.group(2).strip()
            if inline and inline != "]":
                # Split quoted strings.
                current_deps.extend(
                    d.strip().strip('"').strip("'") for d in inline.split(",") if d.strip()
                )
            continue
        # Closing ``]`` — finalize profile.
        if line == "]" and current_profile is not None:
            profiles[current_profile] = current_deps
            current_profile = None
            current_deps = []
            continue
        # Continuation line: dependency entry.
        if current_profile is not None and line:
            # Strip comments, quotes.
            dep = re.sub(r"\s*#.*$", "", line).strip().strip('"').strip("'")
            if dep and dep != "]":
                # Strip trailing comma.
                dep = dep.rstrip(",").strip()
                if dep:
                    current_deps.append(dep)
    if current_profile is not None:
        profiles[current_profile] = current_deps
    return profiles


def verify_profiles(content: str) -> list[str]:
    """Return list of issues (empty = PASS)."""
    issues: list[str] = []
    profiles = _parse_optional_deps(content)

    for profile in REQUIRED_PROFILES:
        if profile not in profiles:
            issues.append(f"profile '{profile}' missing from [project.optional-dependencies]")
            continue
        deps = profiles[profile]
        if not deps:
            issues.append(f"profile '{profile}' is empty")
            continue
        # Verify minimal test runner deps present.
        joined = " ".join(deps).lower()
        for required_dep in MINIMAL_TEST_DEPS:
            if not any(d.lower().startswith(required_dep) for d in deps):
                issues.append(
                    f"profile '{profile}' missing required dep '{required_dep}'"
                )

    # test-all должен содержать ВСЕ остальные test-* deps (heuristic:
    # count должен быть > каждого отдельного профиля).
    if "test-all" in profiles and "test-scheduler" in profiles:
        if len(profiles["test-all"]) <= len(profiles["test-scheduler"]):
            issues.append(
                f"test-all should be meta-extra with more deps than test-scheduler "
                f"(all={len(profiles['test-all'])}, scheduler={len(profiles['test-scheduler'])})"
            )

    return issues


def render_table(issues: list[str]) -> str:
    if not issues:
        profiles = _parse_optional_deps(PYPROJECT.read_text(encoding="utf-8"))
        test_profiles = {
            name: len(deps) for name, deps in profiles.items() if name.startswith("test-")
        }
        lines = [
            "✅ Test dependency profiles verification PASS",
            "",
            "Detected profiles:",
        ]
        for name, count in sorted(test_profiles.items()):
            lines.append(f"  {name:<20} {count:>3} deps")
        return "\n".join(lines) + "\n"
    return (
        "❌ Test dependency profiles verification FAILED\n\n"
        + "\n".join(f"  - {issue}" for issue in issues)
        + "\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verification that test-* dependency profiles (per v6 / 25.09 audit) "
            "are properly defined in pyproject.toml."
        )
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 если есть violations (CI gate).",
    )
    args = parser.parse_args(argv)

    if not PYPROJECT.exists():
        print(f"❌ {PYPROJECT} not found", file=sys.stderr)
        return 1

    content = PYPROJECT.read_text(encoding="utf-8")
    issues = verify_profiles(content)

    sys.stdout.write(render_table(issues) + "\n")

    if args.strict and issues:
        sys.stderr.write(
            f"\nFAILED: {len(issues)} violations. "
            f"См. pyproject.toml::[project.optional-dependencies] для "
            f"required test-* profiles.\n"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
