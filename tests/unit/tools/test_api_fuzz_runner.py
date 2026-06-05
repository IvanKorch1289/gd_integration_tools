"""Sprint 6 K2 — тесты tools/api_fuzz_runner.py."""

# ruff: noqa: S101

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

API_FUZZ_PATH = Path("tools/api_fuzz_runner.py")
ALLOWLIST_PATH = Path("tools/checks/schemathesis_allowlist.json")


def _import_api_fuzz():
    """Подгрузить tools/api_fuzz_runner.py через importlib."""
    spec = importlib.util.spec_from_file_location("_api_fuzz_test", API_FUZZ_PATH)
    if spec is None or spec.loader is None:
        raise ImportError("Не удалось загрузить api_fuzz_runner.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_api_fuzz_runner_exists() -> None:
    """tools/api_fuzz_runner.py существует."""
    assert API_FUZZ_PATH.exists()


def test_allowlist_loadable() -> None:
    """tools/checks/schemathesis_allowlist.json существует и валиден."""
    assert ALLOWLIST_PATH.exists()
    data = json.loads(ALLOWLIST_PATH.read_text())
    assert "version" in data
    assert "violations" in data
    assert isinstance(data["violations"], list)


def test_help_runs() -> None:
    """python tools/api_fuzz_runner.py --help возвращает exit 0."""
    import subprocess

    result = subprocess.run(
        [sys.executable, str(API_FUZZ_PATH), "--help"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0
    assert "--openapi" in result.stdout
    assert "--strict" in result.stdout
    assert "--allowlist" in result.stdout


def test_count_violations_parses_failed_line() -> None:
    """_count_violations извлекает число FAILED из output schemathesis."""
    m = _import_api_fuzz()
    # Symulated schemathesis output
    stdout = """
    Hypothesis: Schemathesis test setup
    .........
    FAILED: 3 test cases
    """
    count = m._count_violations(stdout, "")
    assert count == 3


def test_count_violations_zero_on_clean_output() -> None:
    """_count_violations возвращает 0 если нет FAILED."""
    m = _import_api_fuzz()
    stdout = "All tests passed!"
    assert m._count_violations(stdout, "") == 0


def test_load_allowlist_empty_when_missing(tmp_path: Path) -> None:
    """_load_allowlist возвращает [] если файла нет."""
    m = _import_api_fuzz()
    result = m._load_allowlist(tmp_path / "nonexistent.json")
    assert result == []


def test_load_allowlist_returns_violations(tmp_path: Path) -> None:
    """_load_allowlist возвращает список violations."""
    m = _import_api_fuzz()
    f = tmp_path / "allowlist.json"
    f.write_text(json.dumps({"violations": [{"endpoint": "/x", "check": "y"}]}))
    result = m._load_allowlist(f)
    assert len(result) == 1
    assert result[0]["endpoint"] == "/x"


def test_strict_mode_via_cli(monkeypatch) -> None:
    """_is_strict_mode возвращает True при --strict."""
    m = _import_api_fuzz()
    args = argparse.Namespace(strict=True)
    assert m._is_strict_mode(args) is True

    # ENV переменная также работает
    monkeypatch.setenv("FEATURE_SCHEMATHESIS_GATE_ENABLED", "true")
    args = argparse.Namespace(strict=False)
    assert m._is_strict_mode(args) is True

    # Default (когда ENV пустой) — может быть True/False, важно что не падает.
    monkeypatch.delenv("FEATURE_SCHEMATHESIS_GATE_ENABLED", raising=False)
    args = argparse.Namespace(strict=False)
    result = m._is_strict_mode(args)
    assert isinstance(result, bool)
