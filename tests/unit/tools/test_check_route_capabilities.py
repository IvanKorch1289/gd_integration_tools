"""ADR-0430 — гейт обязательных capability-деклараций роутов и плагинов."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_TOOL = Path("tools/check_route_capabilities.py")


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    """Запустить гейт в текущем репозитории."""
    return subprocess.run(
        [sys.executable, str(_TOOL), *args], capture_output=True, text=True, check=False
    )


def test_gate_passes_on_current_tree() -> None:
    """Текущее состояние репозитория проходит гейт (легаси — в baseline)."""
    result = _run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Capability-декларации: OK" in result.stdout


def test_gate_fails_for_new_manifest_without_declarations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Новый роут без ``net.inbound`` блокируется гейтом."""
    from tools import check_route_capabilities as gate

    routes = tmp_path / "routes"
    new_route = routes / "new_route"
    new_route.mkdir(parents=True)
    (new_route / "route.toml").write_text(
        '[route]\nname = "new_route"\nversion = "0.1.0"\n', encoding="utf-8"
    )

    monkeypatch.setattr(gate, "_ROUTE_DIR", routes)
    monkeypatch.setattr(gate, "_PLUGIN_DIR", tmp_path / "plugins")
    monkeypatch.setattr(gate, "_BASELINE_PATH", tmp_path / "baseline.txt")

    code = gate.main([])
    assert code == 1


def test_gate_accepts_declared_route(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Роут с декларацией ``net.inbound`` проходит."""
    from tools import check_route_capabilities as gate

    routes = tmp_path / "routes"
    new_route = routes / "good_route"
    new_route.mkdir(parents=True)
    (new_route / "route.toml").write_text(
        '[route]\nname = "good_route"\nversion = "0.1.0"\n'
        '[[route.capabilities]]\nname = "net.inbound"\nscope = "http:/api/v1/good"\n',
        encoding="utf-8",
    )

    monkeypatch.setattr(gate, "_ROUTE_DIR", routes)
    monkeypatch.setattr(gate, "_PLUGIN_DIR", tmp_path / "plugins")
    monkeypatch.setattr(gate, "_BASELINE_PATH", tmp_path / "baseline.txt")

    assert gate.main([]) == 0


def test_baseline_file_exists_and_is_not_empty() -> None:
    """Baseline-файл существует (легаси зафиксирован явно)."""
    baseline = Path(".security/route-capabilities-baseline.txt")
    assert baseline.exists(), "нет baseline-файла гейта capability-деклараций"
    entries = [
        line.strip()
        for line in baseline.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    assert entries, "baseline пуст — легаси-манифесты не зафиксированы"
    assert all(":" in entry for entry in entries), entries
