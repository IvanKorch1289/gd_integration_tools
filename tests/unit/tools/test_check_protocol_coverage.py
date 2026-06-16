r"""Tests for tools/check_protocol_coverage.py (S106 W6).

Verifies the protocol coverage check tool uses V22 layout paths
(\`src/backend/entrypoints/\`, \`src/backend/dsl/commands/setup/\`) instead
of the legacy R3.10 paths.

S106 W6 fix: оригинальный check использовал stale \`src/entrypoints/\`
path (R3.10 layout), что приводило к ложным FAIL'ам для 4 существующих
entrypoint handlers (ws/webhook/express/sse). Фактически все 4 файла
с bridge import + dispatch call уже были на месте — нужно было обновить
ТОЛЬКО путь в check tool.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def test_check_uses_v22_layout_entrypoints() -> None:
    """check_protocol_coverage.py использует src/backend/entrypoints."""
    tools_dir = Path(__file__).resolve().parent.parent.parent.parent / "tools"
    check_file = tools_dir / "check_protocol_coverage.py"
    assert check_file.is_file(), f"missing {check_file}"
    text = check_file.read_text(encoding="utf-8")
    # V22 path used
    assert "src/backend/entrypoints" in text, (
        "check_protocol_coverage.py should use V22 path 'src/backend/entrypoints'"
    )
    # Legacy R3.10 path NOT used as primary (may appear in docstring only)
    assert 'ROOT / "src" / "entrypoints"' not in text, (
        "check_protocol_coverage.py still uses legacy R3.10 path"
    )


def test_check_uses_v22_layout_setup() -> None:
    """check_protocol_coverage.py использует src/backend/dsl/commands/setup/."""
    tools_dir = Path(__file__).resolve().parent.parent.parent.parent / "tools"
    check_file = tools_dir / "check_protocol_coverage.py"
    text = check_file.read_text(encoding="utf-8")
    # V22 setup package path
    assert "src/backend/dsl/commands/setup" in text, (
        "check_protocol_coverage.py should use V22 setup package"
    )
    # Legacy setup.py file path NOT used
    assert 'commands / "setup.py"' not in text, (
        "check_protocol_coverage.py still looks for legacy setup.py"
    )


@pytest.mark.parametrize(
    "transport,suffix",
    [
        ("ws", "ws_handler.py"),
        ("webhook", "handler.py"),
        ("express", "router.py"),
        ("sse", "handler.py"),
    ],
)
def test_check_target_paths_are_v22(transport: str, suffix: str) -> None:
    """_TARGETS dict содержит V22 path для каждого transport."""
    tools_dir = Path(__file__).resolve().parent.parent.parent.parent / "tools"
    check_file = tools_dir / "check_protocol_coverage.py"
    text = check_file.read_text(encoding="utf-8")
    # Проверяем что suffix и transport вместе в _TARGETS
    assert f'"{transport}": ENTRYPOINTS /' in text, (
        f"check_protocol_coverage.py missing _TARGETS entry: {transport}"
    )
    assert suffix in text, f"check_protocol_coverage.py missing V22 path part: {suffix}"
    # V22 path parts (для всех 4 transports)
    for v22_part in ("websocket", "webhook", "express", "sse"):
        assert v22_part in text, f"missing V22 path part: {v22_part}"


def test_check_runs_successfully() -> None:
    """Запуск check tool returns exit 0 + [protocol_coverage] OK."""
    import subprocess

    tools_dir = Path(__file__).resolve().parent.parent.parent.parent / "tools"
    check_file = tools_dir / "check_protocol_coverage.py"
    # Use system python since test runs in .venv
    import sys

    python_exe = sys.executable
    result = subprocess.run(
        [python_exe, str(check_file)], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, (
        f"check_protocol_coverage.py failed: stdout={result.stdout!r} "
        f"stderr={result.stderr!r}"
    )
    assert "[protocol_coverage] OK" in result.stdout
    assert "bridge: src/backend/entrypoints/_action_bridge.py" in result.stdout
    for transport in ("ws", "webhook", "express", "sse"):
        assert transport in result.stdout
