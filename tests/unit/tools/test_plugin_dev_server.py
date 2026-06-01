# ruff: noqa: S101
"""Sprint 14 K5 W4 — smoke-тесты ``tools.plugin_dev_server``."""

from __future__ import annotations

import sys
from pathlib import Path

_TOOLS = Path(__file__).resolve().parents[3] / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import plugin_dev_server as pds  # noqa: E402


def test_main_returns_2_when_plugin_missing(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(pds, "_PROJECT_ROOT", tmp_path)
    rc = pds.main(["--name", "absent", "--port", "9090"])
    assert rc == 2


def test_main_sets_env_var(monkeypatch, tmp_path) -> None:
    (tmp_path / "extensions" / "demo").mkdir(parents=True)
    monkeypatch.setattr(pds, "_PROJECT_ROOT", tmp_path)

    started: dict[str, object] = {}

    class _FakeProc:
        returncode = 0

        def send_signal(self, *_args, **_kwargs) -> None:
            return None

        def wait(self) -> int:
            return 0

    def _fake_start(port: int) -> _FakeProc:
        started["port"] = port
        started["env_allowlist"] = pds.os.environ.get("PLUGIN_DEV_ALLOWLIST")
        return _FakeProc()

    monkeypatch.setattr(pds, "_start_backend", _fake_start)
    rc = pds.main(["--name", "demo", "--port", "9091"])
    assert rc == 0
    assert started["port"] == 9091
    assert started["env_allowlist"] == "demo"
