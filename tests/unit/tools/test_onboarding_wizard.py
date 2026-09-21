"""Unit tests for onboarding wizard (tools/wizards/onboarding_wizard.py)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]


def _load_wizard():
    """Загружает onboarding wizard напрямую (tools/ не package)."""
    src = _ROOT / "tools" / "wizards" / "onboarding_wizard.py"
    spec = importlib.util.spec_from_file_location("onboarding_wizard_mod", src)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["onboarding_wizard_mod"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


_wizard = _load_wizard()


@pytest.fixture(autouse=True)
def _silence_console(monkeypatch: pytest.MonkeyPatch) -> None:
    """Отключает rich-вывод в тестах wizard."""
    monkeypatch.setattr(_wizard.console, "print", lambda *args, **kwargs: None)


@pytest.fixture
def all_tools_available(monkeypatch: pytest.MonkeyPatch) -> None:
    """Все pre-flight tools доступны."""
    monkeypatch.setattr(_wizard, "_check_tool", lambda name: True)


class TestPreflightChecks:
    def test_returns_checks(self, all_tools_available) -> None:
        checks = _wizard._preflight_checks(dry_run=True)
        assert all(checks.values())

    def test_missing_required_exits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _fake_check(name: str) -> bool:
            return name not in {"python", "python3"}

        monkeypatch.setattr(_wizard, "_check_tool", _fake_check)
        with pytest.raises(SystemExit):
            _wizard._preflight_checks(dry_run=False)


class TestInstallDeps:
    def test_non_interactive_dry_run(self, monkeypatch: pytest.MonkeyPatch) -> None:
        commands: list[list[str]] = []
        monkeypatch.setattr(
            _wizard, "_run", lambda cmd, **kwargs: commands.append(cmd) or 0
        )
        _wizard._install_deps(non_interactive=True, dry_run=True)
        assert commands == [["uv", "sync", "--all-extras"]]


class TestSamplePlugin:
    def test_non_interactive_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        commands: list[list[str]] = []
        monkeypatch.setattr(
            _wizard, "_run", lambda cmd, **kwargs: commands.append(cmd) or 0
        )
        _wizard._sample_plugin(non_interactive=True, dry_run=False)
        assert commands == []


class TestMain:
    def test_non_interactive_dry_run(
        self, all_tools_available, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        commands: list[list[str]] = []
        monkeypatch.setattr(
            _wizard, "_run", lambda cmd, **kwargs: commands.append(cmd) or 0
        )
        _wizard.main(["--non-interactive", "--dry-run"])
        assert ["uv", "sync", "--all-extras"] in commands
        assert ["make", "doctor"] in commands
