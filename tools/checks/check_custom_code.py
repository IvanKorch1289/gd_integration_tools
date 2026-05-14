"""Custom-code audit через vulture (mortal-code detector).

Назначение:
    Sprint 6 К1 wave [s6/k1-custom-code-audit]. Запускает
    ``vulture --min-confidence 80 src/backend`` и сопоставляет с
    allowlist в ``tools/checks/custom_code_allowlist.txt``.

    Высоко-confident dead code (>80% уверенности) — кандидат на удаление.

Использование:
    python tools/checks/check_custom_code.py
    python tools/checks/check_custom_code.py --strict

feature_flag: custom_code_audit_enabled (default-OFF до калибровки baseline).
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

_DEFAULT_TARGET = Path("src/backend")
_DEFAULT_ALLOWLIST = Path("tools/checks/custom_code_allowlist.txt")
_MIN_CONFIDENCE = 80


def _check_vulture_available() -> bool:
    """Проверяет наличие vulture в PATH."""
    return shutil.which("vulture") is not None


def _load_allowlist(path: Path) -> set[str]:
    """Загружает allowlist — список substrings для игнорирования.

    Args:
        path: путь к файлу с allowlist (по строке).

    Returns:
        множество substring-фильтров.
    """
    if not path.exists():
        return set()
    return {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }


def run_vulture(target: Path) -> list[str]:
    """Запускает vulture и возвращает список findings.

    Args:
        target: путь к коду для анализа.

    Returns:
        список строк-findings от vulture.
    """
    cmd = [
        "vulture",
        str(target),
        f"--min-confidence={_MIN_CONFIDENCE}",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603
    if result.returncode > 3:
        print(f"[ERROR] vulture exit code {result.returncode}", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def filter_findings(findings: list[str], allowlist: set[str]) -> list[str]:
    """Фильтрует findings по allowlist.

    Args:
        findings: список строк от vulture.
        allowlist: множество substring-фильтров.

    Returns:
        отфильтрованные findings (без allowlisted).
    """
    if not allowlist:
        return findings
    return [
        f
        for f in findings
        if not any(allowed in f for allowed in allowlist)
    ]


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="custom-code audit via vulture")
    parser.add_argument("--target", type=Path, default=_DEFAULT_TARGET)
    parser.add_argument("--allowlist", type=Path, default=_DEFAULT_ALLOWLIST)
    parser.add_argument(
        "--strict", action="store_true", help="exit 1 при наличии findings"
    )
    args = parser.parse_args()

    if not _check_vulture_available():
        print("[SKIP] vulture не установлен — custom-code audit пропущен")
        return 0
    if not args.target.exists():
        print(f"[ERROR] target '{args.target}' не существует", file=sys.stderr)
        return 1

    findings = run_vulture(args.target)
    allowlist = _load_allowlist(args.allowlist)
    filtered = filter_findings(findings, allowlist)

    print(
        f"[INFO] vulture: {len(findings)} raw findings, "
        f"{len(filtered)} после allowlist ({len(allowlist)} entries)"
    )
    for f in filtered[:20]:
        print(f"  {f}")
    if len(filtered) > 20:
        print(f"  ... и ещё {len(filtered) - 20} findings")

    if args.strict and filtered:
        return 1
    return 0  # warn-only до baseline калибровки


if __name__ == "__main__":
    sys.exit(main())
