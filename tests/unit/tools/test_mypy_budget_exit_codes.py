"""Meta-test: mypy_budget exit codes per v6 W1 spec.

Per v6 W1: «Mypy wrapper должен различать:
- type errors (exit 1),
- tool failure (exit 2),
- environment failure (exit 3),
- success (exit 0)».
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture()
def module_under_test():
    """Import mypy_budget module for direct main() testing."""
    sys.path.insert(0, str(PROJECT_ROOT))
    try:
        from tools.checks import mypy_budget

        yield mypy_budget
    finally:
        sys.path.pop(0)


class TestMypyBudgetExitCodes:
    """Per v6 W1: 4 distinct exit codes for distinct failure modes."""

    def test_exit_0_on_success(self, module_under_test) -> None:
        """Current code: 8 errors ≤ budget 30 → exit 0."""
        result = module_under_test.main([])
        assert result == 0, (
            f"mypy_budget should exit 0 (errors within budget). Got {result}."
        )

    def test_exit_3_on_environment_failure(
        self, module_under_test, monkeypatch
    ) -> None:
        """subprocess.run raises FileNotFoundError → exit 3 (env failure)."""
        import subprocess as sp

        def _raise_filenotfound(*args, **kwargs):
            raise FileNotFoundError("simulated: python missing")

        monkeypatch.setattr(sp, "run", _raise_filenotfound)
        result = module_under_test.main([])
        assert result == 3, (
            f"mypy_budget should exit 3 on FileNotFoundError. Got {result}."
        )

    def test_exit_3_on_oserror(self, module_under_test, monkeypatch) -> None:
        """subprocess.run raises OSError → exit 3 (env failure)."""
        import subprocess as sp

        def _raise_oserror(*args, **kwargs):
            raise OSError("simulated: permission denied")

        monkeypatch.setattr(sp, "run", _raise_oserror)
        result = module_under_test.main([])
        assert result == 3, f"mypy_budget should exit 3 on OSError. Got {result}."

    def test_exit_1_on_type_errors_over_budget(
        self, module_under_test, monkeypatch
    ) -> None:
        """mypy returns exit 1 with errors > budget → exit 1 (type errors)."""
        fake_proc = type(
            "FakeProc",
            (),
            {
                "returncode": 1,
                "stdout": (
                    "src/x.py:1: error: name 'X' is not defined\n"
                    "src/y.py:2: error: type mismatch\n"
                    "src/z.py:3: error: import error\n"
                ),
                "stderr": "",
            },
        )()
        import subprocess as sp

        monkeypatch.setattr(sp, "run", lambda *a, **kw: fake_proc)
        result = module_under_test.main(["--max", "1"])  # budget=1, errors=3
        assert result == 1, (
            f"mypy_budget should exit 1 when errors > max (type errors). Got {result}."
        )

    def test_exit_2_on_tool_crash(self, module_under_test, monkeypatch) -> None:
        """mypy returns exit code != 0, 1 AND empty errors → exit 2 (tool crash)."""
        fake_proc = type(
            "FakeProc",
            (),
            {"returncode": 139, "stdout": "", "stderr": "Segmentation fault"},
        )()  # segfault
        import subprocess as sp

        monkeypatch.setattr(sp, "run", lambda *a, **kw: fake_proc)
        result = module_under_test.main([])
        assert result == 2, (
            f"mypy_budget should exit 2 on tool crash (segfault etc). Got {result}."
        )
