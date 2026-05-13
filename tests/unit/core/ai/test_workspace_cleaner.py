"""Unit-тесты AIWorkspaceCleaner (V15 R-V15-11, task K3 Sprint-2 Wave 2)."""

# ruff: noqa: S101

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.backend.core.ai.workspace_cleaner import AIWorkspaceCleaner

# ─── Тест 1: no-op при выключенном feature-flag ─────────────────────────────


@pytest.mark.asyncio
async def test_start_noop_when_flag_off(tmp_path: Path) -> None:
    """``start`` не создаёт background-task, если feature-flag выключен (default)."""
    cleaner = AIWorkspaceCleaner(workspace_root=tmp_path)
    # feature_flags.ai_workspace_ttl_cleanup = False по умолчанию.
    await cleaner.start()
    assert cleaner._task is None


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
    assert cleaner._task is None
