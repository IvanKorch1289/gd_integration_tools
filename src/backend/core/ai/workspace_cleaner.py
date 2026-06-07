"""AIWorkspaceCleaner — TTL-cleanup и size-quota для AI-workspace (V15 R-V15-11, R-V15-4).

Назначение:

* Периодическое удаление устаревших AI-workspace директорий (TTL 7 дней).
* Принудительная очистка при превышении size-quota тенанта.
* Управляется feature-flag ``ai_workspace_ttl_cleanup`` (default-OFF).

Layout ожидаемой структуры workspace::

    ${AI_WORKSPACE}/<tenant>/<session>/

Политика удаления:

* Если дата последней модификации каталога ``<session>`` старше TTL → rmtree.
* Если суммарный размер каталога ``<tenant>`` превышает ``max_bytes`` →
  удалять самые старые session-каталоги, пока размер не окажется ниже лимита.

Все операции удаления используют ``shutil.rmtree`` и
``pathlib.Path.unlink(missing_ok=True)`` — безопасно при race condition.

Использование::

    cleaner = AIWorkspaceCleaner(workspace_root=Path("/data/ai_workspace"))
    await cleaner.start()
    ...
    await cleaner.stop()
"""

from __future__ import annotations
from src.backend.infrastructure.logging.factory import get_logger

import asyncio

import shutil
import time
from datetime import UTC, datetime
from pathlib import Path

__all__ = ("AIWorkspaceCleaner",)

_logger = get_logger(__name__)

# Значения по умолчанию.
DEFAULT_TTL_DAYS: int = 7
DEFAULT_MAX_BYTES: int = 500 * 1024 * 1024  # 500 МБ
DEFAULT_INTERVAL_SECONDS: float = 3600.0  # 1 час


def _dir_mtime(path: Path) -> float:
    """Возвращает mtime каталога (ctime как fallback)."""
    try:
        return path.stat().st_mtime
    except OSError:
        return time.time()


def _dir_size(path: Path) -> int:
    """Суммарный размер всех файлов в каталоге (без symlink'ов)."""
    total = 0
    if not path.exists():
        return 0
    for entry in path.rglob("*"):
        try:
            if entry.is_file():
                total += entry.stat().st_size
        except OSError:
            continue
    return total


class AIWorkspaceCleaner:
    """Периодическая очистка AI-workspace: TTL + size quota.

    Args:
        workspace_root: Корень структуры ``${AI_WORKSPACE}/<tenant>/<session>/``.
        interval_seconds: Интервал между запусками cleanup (по умолчанию 3600 с).
        ttl_days: TTL для session-каталогов в днях (по умолчанию 7).
        max_bytes: Максимальный суммарный размер одного tenant-каталога в байтах.
    """

    def __init__(
        self,
        workspace_root: Path,
        *,
        interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
        ttl_days: int = DEFAULT_TTL_DAYS,
        max_bytes: int = DEFAULT_MAX_BYTES,
    ) -> None:
        self._root = workspace_root
        self._interval = interval_seconds
        self._ttl_days = ttl_days
        self._max_bytes = max_bytes
        self._task: asyncio.Task | None = None
        self._stopped: bool = False

    async def start(self) -> None:
        """Запустить фоновый cleanup-loop.

        No-op, если feature-flag ``ai_workspace_ttl_cleanup`` выключен.
        Повторный вызов идемпотентен.
        """
        from src.backend.core.config.features import feature_flags

        if not feature_flags.ai_workspace_ttl_cleanup:
            return
        if self._task is not None and not self._task.done():
            return
        self._stopped = False
        from src.backend.core.utils.task_registry import get_task_registry

        self._task = get_task_registry().create_task(
            self._cleanup_loop(), name="ai-workspace-cleaner"
        )

    async def stop(self) -> None:
        """Остановить фоновый cleanup-loop.

        Идемпотентен: безопасно вызывать до start() или несколько раз.
        """
        self._stopped = True
        task = self._task
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    def cleanup_expired(self, now: datetime, ttl_days: int | None = None) -> int:
        """Удалить session-каталоги старше TTL.

        Обходит ``<workspace_root>/<tenant>/<session>/`` и удаляет
        каталоги, дата последней модификации которых старше ``ttl_days``
        дней от ``now``.

        Args:
            now: Момент «сейчас» (для тестируемости).
            ttl_days: Переопределяет TTL экземпляра (опционально).

        Returns:
            Количество удалённых session-каталогов.
        """
        effective_ttl = ttl_days if ttl_days is not None else self._ttl_days
        cutoff_ts = now.timestamp() - effective_ttl * 86400

        removed = 0
        if not self._root.exists():
            return 0

        for tenant_dir in self._root.iterdir():
            if not tenant_dir.is_dir():
                continue
            for session_dir in tenant_dir.iterdir():
                if not session_dir.is_dir():
                    continue
                mtime = _dir_mtime(session_dir)
                if mtime < cutoff_ts:
                    try:
                        shutil.rmtree(session_dir, ignore_errors=True)
                        removed += 1
                        _logger.info(
                            "ai_workspace_cleaner.expired_removed",
                            extra={
                                "tenant": tenant_dir.name,
                                "session": session_dir.name,
                                "mtime": mtime,
                            },
                        )
                    except OSError as exc:
                        _logger.warning(
                            "ai_workspace_cleaner.remove_failed",
                            extra={"path": str(session_dir), "error": repr(exc)},
                        )
        return removed

    def enforce_size_quota(self, workspace: Path, max_bytes: int | None = None) -> int:
        """Проверить и при необходимости урезать размер tenant-каталога.

        Удаляет самые старые session-директории по mtime, пока суммарный
        размер каталога ``workspace`` не окажется ниже ``max_bytes``.

        Args:
            workspace: Путь к ``<workspace_root>/<tenant>/``.
            max_bytes: Предельный размер в байтах (переопределяет настройку
                экземпляра).

        Returns:
            Количество удалённых session-каталогов.
        """
        limit = max_bytes if max_bytes is not None else self._max_bytes
        if not workspace.exists():
            return 0

        current = _dir_size(workspace)
        if current <= limit:
            return 0

        # Собрать session-каталоги и отсортировать по mtime (старые первыми).
        sessions = sorted(
            (d for d in workspace.iterdir() if d.is_dir()), key=_dir_mtime
        )

        removed = 0
        for session_dir in sessions:
            if current <= limit:
                break
            freed = _dir_size(session_dir)
            try:
                shutil.rmtree(session_dir, ignore_errors=True)
                current = max(0, current - freed)
                removed += 1
                _logger.info(
                    "ai_workspace_cleaner.quota_evicted",
                    extra={
                        "workspace": str(workspace),
                        "session": session_dir.name,
                        "freed_bytes": freed,
                        "remaining_bytes": current,
                    },
                )
            except OSError as exc:
                _logger.warning(
                    "ai_workspace_cleaner.evict_failed",
                    extra={"path": str(session_dir), "error": repr(exc)},
                )
        return removed

    async def _cleanup_loop(self) -> None:
        """Внутренний цикл фоновой очистки."""
        try:
            while not self._stopped:
                await asyncio.sleep(self._interval)
                try:
                    now = datetime.now(tz=UTC)
                    self.cleanup_expired(now)
                    if self._root.exists():
                        for tenant_dir in self._root.iterdir():
                            if tenant_dir.is_dir():
                                self.enforce_size_quota(tenant_dir)
                except Exception as exc:
                    _logger.warning(
                        "ai_workspace_cleaner.loop_error", extra={"error": repr(exc)}
                    )
        except asyncio.CancelledError:
            raise
