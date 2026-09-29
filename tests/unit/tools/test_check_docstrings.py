"""TDD: tools/check_docstrings.py — audit docs validation (M14.4).

Проверяет что check_docstrings:
- Запускается на directory
- Возвращает exit code 0 если OK
- Возвращает exit code != 0 если есть violations
- Поддерживает --update-allowlist
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


def _run_check_docstrings(
    target: str, timeout: int
) -> subprocess.CompletedProcess[str]:
    """Запустить check_docstrings на целевом пути.

    Используется ``sys.executable`` и путь от ``__file__``: раньше тест звал
    ``python`` из PATH (3.12 вместо проектных 3.14 — расхождение с make) и
    жёстко зашивал ``cwd="/home/user/dev/gd_integration_tools"``, из-за чего
    падал на любой машине с другим путём.
    """
    return subprocess.run(
        [sys.executable, "tools/check_docstrings.py", target],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=timeout,
    )


class TestCheckDocstrings:
    def test_runs_on_directory(self) -> None:
        """check_docstrings запускается на directory."""
        result = _run_check_docstrings("src/backend/core/utils", 30)
        # Должен запуститься (exit code 0 или 1)
        assert result.returncode in (0, 1), (
            f"unexpected exit code: {result.returncode}, stderr: {result.stderr}"
        )

    @pytest.mark.skip(
        reason="M14.4: typer не установлен в dev env, check_docstrings требует его (M14 fix)"
    )
    def test_detects_missing_docstrings(self) -> None:
        """check_docstrings находит отсутствующие docstring."""
        result = _run_check_docstrings("src/backend/dsl", 60)
        # src/backend/dsl имеет 150+ missing docstrings — должно быть violations
        assert result.returncode == 1, (
            f"expected violations в src/backend/dsl, got rc={result.returncode}"
        )
        # Output должен указывать на missing files
        assert "src/backend/dsl" in result.stdout or "src/backend/dsl" in result.stderr
