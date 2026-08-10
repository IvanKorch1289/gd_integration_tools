"""Регрессионные тесты baseline-гейтов качества.

Проверяют fail-closed для аварий mypy/pytest и формат mypy baseline.
"""


from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from tools import check_test_baseline
from tools.checks import mypy_budget


@pytest.mark.unit
def test_mypy_budget_process_error_returns_exit_2(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Авария mypy без ошибок не должна давать ложный PASS."""

    def failed_mypy() -> tuple[int, str]:
        return 2, "INTERNAL ERROR"

    monkeypatch.setattr(mypy_budget, "run_mypy", failed_mypy)
    monkeypatch.setattr(mypy_budget, "BASELINE_FILE", tmp_path / "mypy.json")
    monkeypatch.setattr(sys, "argv", ["mypy_budget.py", "--max", "5"])

    assert mypy_budget.main() == 2
    assert "without a valid result" in capsys.readouterr().err


@pytest.mark.unit
def test_mypy_baseline_roundtrip_uses_supported_format(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Mypy baseline хранит целое число ошибок и имя инструмента."""
    baseline = tmp_path / "mypy.json"
    monkeypatch.setattr(mypy_budget, "BASELINE_FILE", baseline)

    mypy_budget.save_baseline(3)

    assert json.loads(baseline.read_text(encoding="utf-8")) == {
        "errors": 3,
        "tool": "mypy",
    }
    assert mypy_budget.load_baseline() == 3


@pytest.mark.unit
def test_test_baseline_default_process_error_returns_exit_2(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Default collect-only не должен скрывать непарсируемую ошибку pytest."""

    def failed_pytest(*, run: bool) -> tuple[int, str]:
        assert run is False
        return 4, "ERROR: file or directory not found"

    monkeypatch.setattr(check_test_baseline, "run_pytest", failed_pytest)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "check_test_baseline.py",
            "--allowlist",
            str(tmp_path / "missing-allowlist.txt"),
        ],
    )

    assert check_test_baseline.main() == 2
    assert "pytest exited with code 4" in capsys.readouterr().err


@pytest.mark.unit
def test_test_baseline_allows_known_collection_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Allowlisted collection error сохраняет штатный exit 0."""
    allowlist = tmp_path / "allowlist.txt"
    allowlist.write_text(
        "tests/unit/test_old.py\tизвестная ошибка коллекции\n", encoding="utf-8"
    )

    def failed_pytest(*, run: bool) -> tuple[int, str]:
        assert run is False
        return 2, "ERROR tests/unit/test_old.py - ImportError"

    monkeypatch.setattr(check_test_baseline, "run_pytest", failed_pytest)
    monkeypatch.setattr(
        sys, "argv", ["check_test_baseline.py", "--allowlist", str(allowlist)]
    )

    assert check_test_baseline.main() == 0
