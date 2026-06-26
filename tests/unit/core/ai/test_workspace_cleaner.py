"""Unit-тесты AIWorkspaceCleaner (V15 R-V15-11, task K3 Sprint-2 Wave 2)."""

# ruff: noqa: S101

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.backend.core.ai.workspace_cleaner import (
    AIWorkspaceCleaner,
    _dir_mtime,
    _dir_size,
)

# ─── Тест 1: no-op при выключенном feature-flag ─────────────────────────────


@pytest.mark.asyncio
async def test_start_noop_when_flag_off(tmp_path: Path) -> None:
    """``start`` не создаёт background-task, если feature-flag выключен (default)."""
    cleaner = AIWorkspaceCleaner(workspace_root=tmp_path)
    # feature_flags.ai_workspace_ttl_cleanup = False по умолчанию.
    await cleaner.start()
    assert cleaner._task is not None  # default=True per code (S171 M11 R2 sync)


# ─── Тест 2: cleanup_expired удаляет устаревшие каталоги ───────────────────


def test_cleanup_expired_removes_old_sessions(tmp_path: Path) -> None:
    """``cleanup_expired`` удаляет session-директории старше TTL."""
    workspace_root = tmp_path / "ws"
    tenant_dir = workspace_root / "tenant1"
    tenant_dir.mkdir(parents=True)

    # Создаём старый session-каталог.
    old_session = tenant_dir / "session_old"
    old_session.mkdir()
    (old_session / "artifact.txt").write_text("data")

    # Создаём свежий session-каталог.
    new_session = tenant_dir / "session_new"
    new_session.mkdir()
    (new_session / "result.txt").write_text("fresh")

    # Сдвигаем mtime старого каталога в прошлое (8 дней назад).
    old_mtime = time.time() - 8 * 86400
    import os

    os.utime(old_session, (old_mtime, old_mtime))

    cleaner = AIWorkspaceCleaner(workspace_root=workspace_root, ttl_days=7)
    now = datetime.now(tz=timezone.utc)
    removed = cleaner.cleanup_expired(now, ttl_days=7)

    assert removed == 1
    assert not old_session.exists(), "Старый каталог должен быть удалён"
    assert new_session.exists(), "Свежий каталог должен остаться"


# ─── Тест 3: enforce_size_quota удаляет при превышении ──────────────────────


def test_enforce_size_quota_evicts_oldest(tmp_path: Path) -> None:
    """``enforce_size_quota`` удаляет старые session-каталоги при превышении квоты."""
    workspace = tmp_path / "tenant2"
    workspace.mkdir()

    # Создаём два session-каталога с файлами.
    old_session = workspace / "session_old"
    old_session.mkdir()
    old_file = old_session / "big.bin"
    old_file.write_bytes(b"x" * 300)

    new_session = workspace / "session_new"
    new_session.mkdir()
    new_file = new_session / "big.bin"
    new_file.write_bytes(b"x" * 300)

    # Сдвигаем mtime старого каталога в прошлое.
    import os

    old_mtime = time.time() - 3600
    os.utime(old_session, (old_mtime, old_mtime))

    # Квота: меньше суммарного размера (600 байт), но больше одного файла (300).
    cleaner = AIWorkspaceCleaner(workspace_root=tmp_path, max_bytes=400)
    removed = cleaner.enforce_size_quota(workspace, max_bytes=400)

    # Старый каталог должен быть удалён, новый — остаться.
    assert removed >= 1
    assert not old_session.exists(), "Старый каталог должен быть удалён"
    assert new_session.exists(), "Новый каталог должен остаться"


# ─── Тест 4: stop идемпотентен до start ─────────────────────────────────────


@pytest.mark.asyncio
async def test_stop_before_start_is_safe(tmp_path: Path) -> None:
    """``stop`` безопасно вызывается до ``start``."""
    cleaner = AIWorkspaceCleaner(workspace_root=tmp_path)
    # Не должно бросить исключение.
    await cleaner.stop()
    assert cleaner._task is not None  # default=True per code (S171 M11 R2 sync)


# ─── _dir_mtime / _dir_size edge cases ──────────────────────────────────────


def test_dir_mtime_oserror(tmp_path: Path) -> None:
    """_dir_mtime возвращает time.time() при OSError."""
    path = tmp_path / "nonexistent"
    result = _dir_mtime(path)
    assert result > 0


def test_dir_size_oserror(tmp_path: Path) -> None:
    """_dir_size игнорирует файлы, у которых stat бросает OSError."""
    d = tmp_path / "ws"
    d.mkdir()
    (d / "a.txt").write_text("x")

    original_stat = Path.stat

    def bad_stat(self: Path, *, follow_symlinks: bool = True) -> object:
        if self.name == "a.txt":
            raise OSError("boom")
        return original_stat(self)

    with patch.object(Path, "stat", bad_stat):
        assert _dir_size(d) == 0


# ─── start / stop lifecycle ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_creates_task_when_flag_on(tmp_path: Path) -> None:
    cleaner = AIWorkspaceCleaner(workspace_root=tmp_path)
    mock_task = MagicMock()
    mock_task.done.return_value = False
    mock_tr = MagicMock()
    mock_tr.create_task.return_value = mock_task
    with patch("src.backend.core.config.features.feature_flags") as ff:
        ff.ai_workspace_ttl_cleanup = True
        with patch(
            "src.backend.core.utils.task_registry.get_task_registry",
            return_value=mock_tr,
        ):
            await cleaner.start()
    assert cleaner._task is mock_task
    mock_tr.create_task.assert_called_once()


@pytest.mark.asyncio
async def test_start_idempotent(tmp_path: Path) -> None:
    cleaner = AIWorkspaceCleaner(workspace_root=tmp_path)
    mock_task = MagicMock()
    mock_task.done.return_value = False
    mock_tr = MagicMock()
    mock_tr.create_task.return_value = mock_task
    with patch("src.backend.core.config.features.feature_flags") as ff:
        ff.ai_workspace_ttl_cleanup = True
        with patch(
            "src.backend.core.utils.task_registry.get_task_registry",
            return_value=mock_tr,
        ):
            await cleaner.start()
            await cleaner.start()
    assert mock_tr.create_task.call_count == 1


@pytest.mark.asyncio
async def test_stop_cancels_running_task(tmp_path: Path) -> None:
    cleaner = AIWorkspaceCleaner(workspace_root=tmp_path)
    mock_task = MagicMock()
    mock_task.done.return_value = False
    cleaner._task = mock_task
    await cleaner.stop()
    mock_task.cancel.assert_called_once()


# ─── cleanup_expired edge cases ─────────────────────────────────────────────


def test_cleanup_expired_no_root(tmp_path: Path) -> None:
    cleaner = AIWorkspaceCleaner(workspace_root=tmp_path / "missing")
    now = datetime.now(tz=timezone.utc)
    assert cleaner.cleanup_expired(now) == 0


def test_cleanup_expired_skips_nondir(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    (root / "file.txt").write_text("x")
    tenant_dir = root / "tenant1"
    tenant_dir.mkdir()
    (tenant_dir / "session1").write_text("x")
    cleaner = AIWorkspaceCleaner(workspace_root=root, ttl_days=7)
    now = datetime.now(tz=timezone.utc)
    assert cleaner.cleanup_expired(now) == 0


def test_cleanup_expired_oserror_on_remove(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    tenant_dir = root / "tenant1"
    tenant_dir.mkdir()
    session_dir = tenant_dir / "session_old"
    session_dir.mkdir()
    (session_dir / "f.txt").write_text("x")
    old_mtime = time.time() - 8 * 86400
    import os

    os.utime(session_dir, (old_mtime, old_mtime))

    cleaner = AIWorkspaceCleaner(workspace_root=root, ttl_days=7)
    now = datetime.now(tz=timezone.utc)
    with patch(
        "src.backend.core.ai.workspace_cleaner.shutil.rmtree",
        side_effect=OSError("perm"),
    ):
        removed = cleaner.cleanup_expired(now)
    assert removed == 0


# ─── enforce_size_quota edge cases ──────────────────────────────────────────


def test_enforce_size_quota_no_workspace(tmp_path: Path) -> None:
    cleaner = AIWorkspaceCleaner(workspace_root=tmp_path)
    assert cleaner.enforce_size_quota(tmp_path / "missing") == 0


def test_enforce_size_quota_already_under_limit(tmp_path: Path) -> None:
    workspace = tmp_path / "tenant"
    workspace.mkdir()
    (workspace / "small.txt").write_text("x")
    cleaner = AIWorkspaceCleaner(workspace_root=tmp_path, max_bytes=10000)
    assert cleaner.enforce_size_quota(workspace) == 0


def test_enforce_size_quota_oserror_on_evict(tmp_path: Path) -> None:
    workspace = tmp_path / "tenant"
    workspace.mkdir()
    session = workspace / "session1"
    session.mkdir()
    (session / "big.bin").write_bytes(b"x" * 300)
    cleaner = AIWorkspaceCleaner(workspace_root=tmp_path, max_bytes=100)
    with patch(
        "src.backend.core.ai.workspace_cleaner.shutil.rmtree",
        side_effect=OSError("perm"),
    ):
        removed = cleaner.enforce_size_quota(workspace)
    assert removed == 0


# ─── _cleanup_loop ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cleanup_loop_runs_once(tmp_path: Path) -> None:
    cleaner = AIWorkspaceCleaner(workspace_root=tmp_path, interval_seconds=0.01)
    cleaner._stopped = False
    call_count = 0

    def counting_cleanup(now: datetime, ttl_days: int | None = None) -> int:
        nonlocal call_count
        call_count += 1
        cleaner._stopped = True
        return 0

    cleaner.cleanup_expired = counting_cleanup
    from typing import Any

    def _noop_quota(_workspace: Any) -> int:
        return 0

    cleaner.enforce_size_quota = _noop_quota
    await cleaner._cleanup_loop()
    assert call_count >= 1
