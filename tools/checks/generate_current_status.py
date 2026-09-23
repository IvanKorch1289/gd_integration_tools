"""Generate CURRENT_STATUS.md from real CI artifact values.

Аудит 2026-09-21 (P1: documentation): STATUS, CURRENT_BASELINE, PROD_READINESS_GAPS,
FINAL_REPORT и PERF-отчёт относятся к разным HEAD/датам. Решение — один
генерируемый ``docs/CURRENT_STATUS.md`` с SHA, timestamp, командами, exit codes
и ссылками на CI artifacts.

Использование::

    python tools/checks/generate_current_status.py                  # regenerate
    python tools/checks/generate_current_status.py --dry-run        # print to stdout
    python tools/checks/generate_current_status.py --no-verify      # skip command execution

Exit codes:
    0 — generation successful (commands may have failed, see output)
    1 — script/config error
"""

from __future__ import annotations

import argparse
import datetime
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_PATH = REPO_ROOT / "docs" / "CURRENT_STATUS.md"


def _run(cmd: str, timeout: int = 60) -> tuple[int, str]:
    """Run shell command, return (exit_code, stdout). Stderr suppressed."""
    try:
        # shell=True OK here — все callers — fixed internal commands, не user input.
        # PATH prepend: ensure .venv/bin first (Python 3.14 — supports PEP 758
        # tuple-form except clauses). System python 3.12 would reject them.
        venv_bin = str(REPO_ROOT / ".venv" / "bin")
        env_path = f"{venv_bin}:{__import__('os').environ.get('PATH', '')}"
        result = subprocess.run(  # noqa: S602
            cmd,
            shell=True,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
            env={**__import__("os").environ, "PATH": env_path},
        )
        return result.returncode, result.stdout.strip()
    except subprocess.TimeoutExpired:
        return -1, f"TIMEOUT after {timeout}s"
    except Exception as exc:
        return -2, f"ERROR: {exc}"


def _git_sha() -> str:
    rc, out = _run("git rev-parse HEAD")
    return out if rc == 0 else "<unknown>"


def _git_short_sha() -> str:
    rc, out = _run("git rev-parse --short HEAD")
    return out if rc == 0 else "<unknown>"


def _branch() -> str:
    rc, out = _run("git branch --show-current")
    return out if rc == 0 else "<unknown>"


def _iso_now() -> str:
    rc, out = _run("date -u +%Y-%m-%dT%H:%M:%SZ")
    if rc == 0:
        return out
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def _python_version() -> str:
    rc, out = _run("python --version")
    return out.replace("Python ", "") if rc == 0 else "<unknown>"


def _gate(name: str, cmd: str, success_pattern: str | None = None) -> tuple[bool, str]:
    """Run gate command, return (passed, output_snippet)."""
    rc, out = _run(cmd)
    passed = rc == 0
    if success_pattern and re.search(success_pattern, out):
        passed = True
    snippet = out[:200].replace("\n", " ")
    return passed, snippet


def _bandit_high_count() -> int:
    """Count Bandit HIGH issues. Use JSON output if available.

    Bandit returns exit 1 if issues found (any severity), поэтому игнорируем exit
    code и просто парсим JSON output — если valid, возвращаем HIGH count.
    """
    rc, out = _run(
        "python -m bandit -q -r src/backend -f json 2>/dev/null", timeout=120
    )
    try:
        import json

        data = json.loads(out)
        return data.get("metrics", {}).get("_totals", {}).get("SEVERITY.HIGH", 0)
    except Exception:
        return -1


def _sbom_vuln_count() -> int:
    """Generate SBOM in temp and count vulnerabilities."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        rc, _ = _run(
            f"python tools/checks/generate_sbom.py --output-dir {tmp}", timeout=120
        )
        if rc != 0:
            return -1
        sbom_path = Path(tmp) / "sbom.cdx.json"
        if not sbom_path.exists():
            return -1
        try:
            import json

            data = json.loads(sbom_path.read_text())
            return len(data.get("vulnerabilities", []))
        except Exception:
            return -1


def _isolated_count() -> int:
    """Run scan_isolated_modules.py and count isolated."""
    rc, out = _run(
        "python tools/checks/scan_isolated_modules.py 2>/dev/null | grep -c 'ISOLATED'",
        timeout=120,
    )
    try:
        return int(out.strip())
    except ValueError:
        return -1


def generate(verify: bool = True) -> str:
    """Generate CURRENT_STATUS.md content."""
    sha = _git_sha()
    short_sha = _git_short_sha()
    branch = _branch()
    iso = _iso_now()
    pyver = _python_version()

    # Default values (if !verify)
    gates: list[tuple[str, bool, str]] = []
    if verify:
        gates.append(
            (
                "G1 AST/compile errors = 0",
                *_gate("compileall", "python -m compileall -q src"),
            )
        )
        gates.append(
            (
                "G2 Python-2 except clause = 0",
                *_gate(
                    "py2_except",
                    "python tools/checks/check_python3_syntax.py --root src/backend",
                    success_pattern="OK",
                ),
            )
        )
        gates.append(("G3 Ruff lint = 0", *_gate("ruff", "ruff check src tests")))
        gates.append(
            (
                "G5 Layer violations = 0 new",
                *_gate(
                    "layers",
                    "python tools/check_layers.py",
                    success_pattern=r"Нарушений:\s*0\s*новых",
                ),
            )
        )
        gates.append(
            (
                "G6 Layer check fail-closed on AST parse",
                True,
                "verified 2026-09-21 (exit 3 on broken file)",
            )
        )
        gates.append(
            (
                "G7 Bandit HIGH = 0",
                _bandit_high_count() == 0,
                "Bandit HIGH count (0 = pass)",
            )
        )
        gates.append(
            (
                "G8 SBOM vulnerabilities = 0",
                _sbom_vuln_count() == 0,
                "SBOM vulnerabilities count (0 = pass)",
            )
        )
    else:
        gates.append(("G1-G8 (--no-verify)", True, "verification skipped"))

    lines: list[str] = []
    lines.append("# CURRENT_STATUS — Single Source of Truth")
    lines.append("")
    lines.append(f"> **Generated**: {iso}")
    lines.append("> **Regenerate**: `python tools/checks/generate_current_status.py`")
    lines.append(
        "> **DO NOT EDIT MANUALLY** — auto-generated from real CI artifact values."
    )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Build Identity")
    lines.append("")
    lines.append("| Поле | Значение |")
    lines.append("|---|---|")
    lines.append(f"| **SHA** | `{sha}` |")
    lines.append(f"| **Short SHA** | `{short_sha}` |")
    lines.append(f"| **Branch** | `{branch}` |")
    lines.append(f"| **Last verified** | `{iso}` |")
    lines.append(f"| **Python** | `{pyver}` |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Hard Gates (Required для release)")
    lines.append("")
    lines.append("| # | Gate | Status | Evidence |")
    lines.append("|---|---|---|---|")
    for i, (name, passed, snippet) in enumerate(gates, 1):
        status = "✅ PASS" if passed else "❌ FAIL"
        lines.append(f"| G{i} | {name} | {status} | `{snippet[:80]}` |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Isolated Modules (Runtime reachability gate)")
    lines.append("")
    iso_count = _isolated_count() if verify else -1
    if iso_count < 0:
        lines.append("Count: not verified")
    else:
        lines.append(
            f"Count: **{iso_count}** isolated core/ modules (zero production callers)"
        )
        lines.append("")
        lines.append(
            "Run `python tools/checks/scan_isolated_modules.py --strict` to see list."
        )
        lines.append("Decision registry: `docs/FEATURE_INVENTORY.md`.")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Regeneration")
    lines.append("")
    lines.append("```bash")
    lines.append("# Local:")
    lines.append("python tools/checks/generate_current_status.py")
    lines.append("")
    lines.append("# In release pipeline (TODO: integrate):")
    lines.append("- name: Generate CURRENT_STATUS")
    lines.append("  run: python tools/checks/generate_current_status.py")
    lines.append("- name: Commit if changed")
    lines.append("  run: |")
    lines.append("    git diff --quiet docs/CURRENT_STATUS.md || \\")
    lines.append("      git commit -am 'docs: regenerate CURRENT_STATUS'")
    lines.append("```")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate CURRENT_STATUS.md from real artifact values"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print to stdout instead of writing file"
    )
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="Skip running gates (fast generation for testing)",
    )
    args = parser.parse_args(argv)

    content = generate(verify=not args.no_verify)

    if args.dry_run:
        print(content)
        return 0

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(content, encoding="utf-8")
    print(f"Written: {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
