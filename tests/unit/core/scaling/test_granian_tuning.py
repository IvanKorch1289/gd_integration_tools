"""Sprint 6 K2 — тесты GranianTuning (ADR-0059)."""

# ruff: noqa: S101, SLF001

from __future__ import annotations

import os
from unittest.mock import patch


def _import_granian_tuning():
    """Импорт granian_tuning модуля (lazy для теста)."""
    from src.backend.core.scaling.granian_tuning import GranianTuning

    return GranianTuning


def test_resolved_workers_auto() -> None:
    """workers='auto' резолвится в NCPU с min=2, max=max_workers."""
    GranianTuning = _import_granian_tuning()
    cfg = GranianTuning(workers="auto", max_workers=16)
    ncpu = os.cpu_count() or 2
    expected = max(2, min(ncpu, 16))
    assert cfg.resolved_workers == expected, (
        f"ожидалось {expected}, получено {cfg.resolved_workers}"
    )


def test_resolved_workers_explicit() -> None:
    """Явно заданный workers — возвращается как есть."""
    GranianTuning = _import_granian_tuning()
    cfg = GranianTuning(workers=6)
    assert cfg.resolved_workers == 6


def test_resolved_blocking_threads_auto() -> None:
    """blocking_threads='auto' = resolved_workers * 4."""
    GranianTuning = _import_granian_tuning()
    cfg = GranianTuning(workers=4, blocking_threads="auto")
    assert cfg.resolved_blocking_threads == 16


def test_resolved_blocking_threads_explicit() -> None:
    """Явно заданный blocking_threads — возвращается как есть."""
    GranianTuning = _import_granian_tuning()
    cfg = GranianTuning(blocking_threads=32)
    assert cfg.resolved_blocking_threads == 32


def test_resolved_interface_with_rsgi_flag_off() -> None:
    """При granian_rsgi_mode_enabled=False — interface принудительно asgi."""
    GranianTuning = _import_granian_tuning()
    cfg = GranianTuning(interface="rsgi")

    # Patch feature_flag через runtime атрибут.
    with patch(
        "src.backend.core.config.features.feature_flags.granian_rsgi_mode_enabled",
        False,
    ):
        assert cfg.resolved_interface == "asgi"


def test_resolved_interface_with_rsgi_flag_on() -> None:
    """При granian_rsgi_mode_enabled=True — interface=rsgi возвращается как есть."""
    GranianTuning = _import_granian_tuning()
    cfg = GranianTuning(interface="rsgi")

    with patch(
        "src.backend.core.config.features.feature_flags.granian_rsgi_mode_enabled",
        True,
    ):
        assert cfg.resolved_interface == "rsgi"


def test_build_cli_command_has_required_flags() -> None:
    """CLI-команда содержит --interface, --workers, --loop, --threads, app."""
    GranianTuning = _import_granian_tuning()
    cfg = GranianTuning(workers=4, blocking_threads=16, loop="uvloop")

    with patch(
        "src.backend.core.config.features.feature_flags.granian_rsgi_mode_enabled",
        True,
    ):
        cmd = cfg.build_cli_command(app="src.main:app", host="0.0.0.0", port=8000)

    assert "granian" == cmd[0]
    assert "--interface" in cmd
    assert "--workers" in cmd
    assert "4" in cmd  # workers=4
    assert "--loop" in cmd
    assert "uvloop" in cmd
    assert "--threads" in cmd
    assert "16" in cmd  # blocking_threads=16
    assert "src.main:app" == cmd[-1]


def test_build_cli_command_access_log_toggle() -> None:
    """access_log=False не добавляет --access-log."""
    GranianTuning = _import_granian_tuning()
    cfg_on = GranianTuning(access_log=True)
    cfg_off = GranianTuning(access_log=False)

    cmd_on = cfg_on.build_cli_command(app="src.main:app")
    cmd_off = cfg_off.build_cli_command(app="src.main:app")

    assert "--access-log" in cmd_on
    assert "--access-log" not in cmd_off
