"""S73 W1 — TD-S64 / FINAL_REPORT_V2 P0-A closure: regression test для
``tools/fix_except_bug.py`` codemod.

Гарантирует, что в ``src/`` НЕ осталось ``except A, B as e:``
(биндинг без скобок — SyntaxError в Python 3.14, ADR-0304).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3] / "src"
# ADR-0304: ``except A, B:`` без скобок канонична (PEP 758, ruff format).
# Реальный хазард — биндинг ``except A, B as e:`` (SyntaxError под 3.14).
PATTERN = re.compile(
    r"^\s*except\s+[A-Z][a-zA-Z_]*(?:\.[A-Z][a-zA-Z_]+)*"
    r"(?:\s*,\s*[A-Z][a-zA-Z_]*(?:\.[A-Z][a-zA-Z_]+)*)+\s+as\s+",
    re.MULTILINE,
)


def _scan_for_legacy_except(root: Path) -> list[tuple[str, int, str]]:
    """Возвращает список (path, line, match) для каждого legacy
    ``except A, B:`` pattern в *.py файлах под root.
    """
    findings: list[tuple[str, int, str]] = []
    for py_file in root.rglob("*.py"):
        # Skip __pycache__ and venv
        if "__pycache__" in py_file.parts:
            continue
        try:
            content = py_file.read_text(encoding="utf-8")
        except UnicodeDecodeError, OSError:
            continue
        for m in PATTERN.finditer(content):
            line_no = content[: m.start()].count("\n") + 1
            rel = py_file.relative_to(ROOT.parent)
            findings.append((str(rel), line_no, m.group(0).strip()))
    return findings


@pytest.mark.pre_existing
def test_no_legacy_except_a_b_in_src() -> None:
    """Final REPORT_V2 P0-A: 0 файлов с ``except A, B:`` semantic bug.

    Базовый count = 83 файла (по FINAL_REPORT_V2 fact-check 2026-06-12).
    После S73 W1 batch codemod должно быть 0.

    M2.3 review O-4: pre-existing baseline failure (Cycle 36 audit).
    NOT new regression — streamlit ``render.py:106`` содержит
    legacy ``except ValueError, AttributeError:``.
    """
    findings = _scan_for_legacy_except(ROOT)
    if findings:
        msg = "\n".join(
            f"  {path}:{line}: {match}" for path, line, match in findings[:20]
        )
        pytest.fail(
            f"Found {len(findings)} legacy 'except A, B:' patterns in src/. "
            f"Run: python tools/fix_except_bug.py src/\n"
            f"First 20:\n{msg}"
        )


# ADR-0304: ``except A, B:`` без скобок канонична (PEP 758) и семантически
# ЭКВИВАЛЕНТНА ``except (A, B):``. Проект требует Python >=3.14,<3.15
# (pyproject.toml requires-python), поэтому «except A, B: ловит только A»
# невозможно ни на одной поддерживаемой версии. Старый тест требовал, чтобы
# codemod обнулил 194 sites в 155 файлах — чисто косметическая правка без
# изменения поведения, и она прямо противоречила ADR-0304. Тест снят, а
# настоящий хазард (биндинг ``except A, B as e:``) проверяется выше.
def test_codemod_removed_after_pep758() -> None:
    """Документирует снятие codemod-гейта согласно ADR-0304.

    Оставлен как явная точка отсчёта: если поддержка Python < 3.14 вернётся,
    гейт на «0 unparenthesised tuples» нужно будет восстановить вместе с
    неймингом ошибки, который до 3.14 был реальным.
    """
    assert sys.version_info >= (3, 14), (
        "На Python < 3.14 форма ``except A, B:`` связывает B как имя "
        "исключения, а не ловит оба типа — тогда гейт снова становится "
        "осмысленным, и его нужно вернуть."
    )
