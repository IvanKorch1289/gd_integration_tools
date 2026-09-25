"""Тесты для dsl_simulate CLI (S10 K5 W3)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_module():
    path = Path(__file__).resolve().parents[3] / "tools" / "dsl_simulate.py"
    spec = importlib.util.spec_from_file_location("_dsl_simulate_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


mod = _load_module()


def test_resolve_route_path_for_file(tmp_path: Path) -> None:
    f = tmp_path / "x.yaml"
    f.write_text("route_id: x\nsteps: []\n", encoding="utf-8")
    assert mod._resolve_route_path(str(f)) == f


def test_resolve_route_path_for_route_name_dir(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "routes" / "my_route").mkdir(parents=True)
    (tmp_path / "routes" / "my_route" / "main.dsl.yaml").write_text(
        "route_id: my_route\nsteps: []\n", encoding="utf-8"
    )
    assert mod._resolve_route_path("my_route").name == "main.dsl.yaml"


def test_resolve_route_path_missing_raises() -> None:
    import pytest

    with pytest.raises(FileNotFoundError):
        mod._resolve_route_path("nonexistent_route_xyz")


def test_main_runs_dry_run_on_file(tmp_path: Path, monkeypatch, capsys) -> None:
    f = tmp_path / "demo.yaml"
    f.write_text(
        "route_id: demo\nsteps:\n  - call_function: { ref: m:f }\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)


def test_simulate_deterministic_for_same_seed(tmp_path: Path) -> None:
    """W6 audit: «gd route simulate — deterministic clock/UUID/random seed».

    Same seed → same total duration. Проверяет что simulate НЕ
    зависит от wall-clock time (нет time.time() / datetime.now() в random path).
    """
    import subprocess

    f = tmp_path / "demo.yaml"
    f.write_text(
        "route_id: demo\nsteps:\n  - call_function: { ref: m:f }\n  - http_call: { url: https://test }\n",
        encoding="utf-8",
    )
    cmd = [
        sys.executable,
        str(Path(__file__).resolve().parents[3] / "tools" / "dsl_simulate.py"),
        str(f),
        "--seed",
        "42",
        "--json",
    ]
    r1 = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    r2 = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    assert r1.returncode == 0
    assert r2.returncode == 0
    import json

    d1, d2 = json.loads(r1.stdout), json.loads(r2.stdout)
    total1 = sum(s["duration_ms"] for s in d1["steps"])
    total2 = sum(s["duration_ms"] for s in d2["steps"])
    assert abs(total1 - total2) < 0.01, (
        f"Same seed MUST produce deterministic output (audit W6). "
        f"Got {total1} vs {total2}."
    )


def test_simulate_no_wall_clock_dependency(tmp_path: Path) -> None:
    """W6 audit: simulate MUST NOT depend on wall-clock time.

    Проверяет что между двумя runs с PAUSE нет drift — deterministic seed
    гарантирует identical output даже с задержкой между runs.
    """
    import subprocess
    import time

    f = tmp_path / "demo.yaml"
    f.write_text(
        "route_id: demo\nsteps:\n  - call_function: { ref: m:f }\n",
        encoding="utf-8",
    )
    cmd = [
        sys.executable,
        str(Path(__file__).resolve().parents[3] / "tools" / "dsl_simulate.py"),
        str(f),
        "--seed",
        "42",
        "--json",
    ]
    r1 = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    time.sleep(1.0)  # 1 sec pause to ensure wall-clock advanced
    r2 = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    import json

    d1, d2 = json.loads(r1.stdout), json.loads(r2.stdout)
    # Total duration (sum of step durations) MUST be identical — proves
    # no wall-clock dependency.
    total1 = sum(s["duration_ms"] for s in d1["steps"])
    total2 = sum(s["duration_ms"] for s in d2["steps"])
    assert abs(total1 - total2) < 0.01, (
        f"After 1s pause, totals MUST be identical (no wall-clock). "
        f"Got {total1} vs {total2}."
    )


def test_main_runs_dry_run_on_file(tmp_path: Path, monkeypatch, capsys) -> None:
    f = tmp_path / "demo.yaml"
    f.write_text(
        "route_id: demo\nsteps:\n  - call_function: { ref: m:f }\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    code = mod.main([str(f)])
    out = capsys.readouterr().out
    assert code == 0
    assert "Route:" in out
    assert "Waterfall:" in out


def test_main_json_format(tmp_path: Path, monkeypatch, capsys) -> None:
    import json as _json

    f = tmp_path / "demo.yaml"
    f.write_text("route_id: j\nsteps:\n  - audit: { action: ok }\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    mod.main([str(f), "--json"])
    out = capsys.readouterr().out
    data = _json.loads(out)
    assert data["route_id"] == "j"
    assert isinstance(data["steps"], list)
