"""S73 W1 — TD-S64 / FINAL_REPORT_V2 P0-A closure: regression test для
``tools/fix_except_bug.py`` codemod.

Гарантирует, что в ``src/`` НЕ осталось ``except A, B:`` (semantic bug,
не syntax error в Python 3.14). Если новый код вводит такой pattern
— этот тест fail'нет, сигнализируя о semantic bug.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3] / "src"
# Match ``except X, Y, Z:`` (NOT in parens), X is upper-case identifier.
# Исключает legitimate ``except X, e:`` (single-letter alias binding).
PATTERN = re.compile(
    r"^\s*except\s+[A-Z][a-zA-Z_]*(?:\.[A-Z][a-zA-Z_]+)*"
    r"(?:\s*,\s*[A-Z][a-zA-Z_]*(?:\.[A-Z][a-zA-Z_]+)*)+\s*:",
    re.MULTILINE,
)


def _scan_for_legacy_except(root: Path) -> list[tuple[str, int, str]]:
    """Возвращает список (path, line, match) для каждого legacy
    ``except A, B:`` pattern в *.py файлах под root."""
    findings: list[tuple[str, int, str]] = []
    for py_file in root.rglob("*.py"):
        # Skip __pycache__ and venv
        if "__pycache__" in py_file.parts:
            continue
        try:
            content = py_file.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for m in PATTERN.finditer(content):
            line_no = content[: m.start()].count("\n") + 1
            rel = py_file.relative_to(ROOT.parent)
            findings.append((str(rel), line_no, m.group(0).strip()))
    return findings


def test_no_legacy_except_a_b_in_src() -> None:
    """Final REPORT_V2 P0-A: 0 файлов с ``except A, B:`` semantic bug.

    Базовый count = 83 файла (по FINAL_REPORT_V2 fact-check 2026-06-12).
    После S73 W1 batch codemod должно быть 0.
    """
    findings = _scan_for_legacy_except(ROOT)
    if findings:
        msg = "\n".join(
            f"  {path}:{line}: {match}"
            for path, line, match in findings[:20]
        )
        pytest.fail(
            f"Found {len(findings)} legacy 'except A, B:' patterns in src/. "
            f"Run: python tools/fix_except_bug.py src/\n"
            f"First 20:\n{msg}"
        )


def test_codemod_idempotent() -> None:
    """``tools/fix_except_bug.py`` ДОЛЖЕН быть idempotent (можно
    запускать многократно без изменений). Запускаем dry-run и
    проверяем, что 0 changes после первого прогона."""
    import subprocess

    result = subprocess.run(
        ["python", "tools/fix_except_bug.py", "--dry-run", "src/"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"codemod failed: {result.stderr}"
    # Second run должен быть no-op
    assert "0 total fixes" in result.stdout or "0 changes" in result.stdout, (
        f"codemod NOT idempotent — second run found changes:\n{result.stdout}"
    )
