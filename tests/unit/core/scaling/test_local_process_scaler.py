"""Tests for core/scaling/local_process_scaler.py (S101 — coverage push).

LocalProcessScaler: Granian SIGUSR1/SIGUSR2 fork-worker scaler.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def test_init_validates_min_workers() -> None:
    """LocalProcessScaler: min_workers < 1 → ValueError."""
    from src.backend.core.scaling.local_process_scaler import LocalProcessScaler

    with pytest.raises(ValueError, match="min_workers"):
        LocalProcessScaler(min_workers=0)


def test_init_validates_max_workers() -> None:
    """LocalProcessScaler: max_workers < min_workers → ValueError."""
    from src.backend.core.scaling.local_process_scaler import LocalProcessScaler

    with pytest.raises(ValueError, match="max_workers"):
        LocalProcessScaler(min_workers=5, max_workers=3)


def test_init_defaults() -> None:
    """LocalProcessScaler: defaults min=2, max=10, master_pid_file=/run/granian/master.pid."""
    from src.backend.core.scaling.local_process_scaler import LocalProcessScaler

    s = LocalProcessScaler()
    assert s.min_workers == 2
    assert s.max_workers == 10
    assert s.master_pid_file == Path("/run/granian/master.pid")


def test_init_custom_pid_file() -> None:
    """LocalProcessScaler: custom master_pid_file as string."""
    from src.backend.core.scaling.local_process_scaler import LocalProcessScaler

    s = LocalProcessScaler(master_pid_file="/tmp/test.pid")
    assert s.master_pid_file == Path("/tmp/test.pid")


def test_read_master_pid_no_file(tmp_path: Path) -> None:
    """_read_master_pid: missing file → None."""
    from src.backend.core.scaling.local_process_scaler import LocalProcessScaler

    s = LocalProcessScaler(master_pid_file=str(tmp_path / "nonexistent.pid"))
    assert s._read_master_pid() is None


def test_read_master_pid_valid(tmp_path: Path) -> None:
    """_read_master_pid: valid file → int pid."""
    from src.backend.core.scaling.local_process_scaler import LocalProcessScaler

    pid_file = tmp_path / "master.pid"
    pid_file.write_text("12345\n")
    s = LocalProcessScaler(master_pid_file=str(pid_file))
    assert s._read_master_pid() == 12345


def test_read_master_pid_invalid(tmp_path: Path) -> None:
    """_read_master_pid: invalid content → None."""
    from src.backend.core.scaling.local_process_scaler import LocalProcessScaler

    pid_file = tmp_path / "master.pid"
    pid_file.write_text("not-a-number")
    s = LocalProcessScaler(master_pid_file=str(pid_file))
    assert s._read_master_pid() is None


def test_scale_up_no_pid_returns_false(tmp_path: Path) -> None:
    """scale_up: master_pid=None → False (NoOp fallback)."""
    from src.backend.core.scaling.local_process_scaler import LocalProcessScaler

    s = LocalProcessScaler(master_pid_file=str(tmp_path / "missing.pid"))
    assert s.scale_up(by=1) is False


def test_scale_down_no_pid_returns_false(tmp_path: Path) -> None:
    """scale_down: master_pid=None → False (NoOp fallback)."""
    from src.backend.core.scaling.local_process_scaler import LocalProcessScaler

    s = LocalProcessScaler(master_pid_file=str(tmp_path / "missing.pid"))
    assert s.scale_down(by=1) is False


def test_current_workers_no_psutil(tmp_path: Path) -> None:
    """current_workers: psutil missing → returns min_workers (best-effort)."""
    from src.backend.core.scaling.local_process_scaler import LocalProcessScaler

    s = LocalProcessScaler(min_workers=2, master_pid_file=str(tmp_path / "x.pid"))
    # Patch psutil to be unavailable.
    with patch.dict("sys.modules", {"psutil": None}):
        result = s.current_workers()
    assert result == 2  # min_workers fallback


def test_local_process_scaler_dunder_all() -> None:
    """__all__ = ('LocalProcessScaler',)."""
    from src.backend.core.scaling import local_process_scaler

    assert local_process_scaler.__all__ == ("LocalProcessScaler",)
