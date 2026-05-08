"""AIWorkspaceManager — изолированные writable-каталоги для AI (V15 R-V15-4).

Layout::

    ${AI_WORKSPACE}/<tenant>/<session>/<artifact>

Свойства:

* TTL=7 дней по умолчанию (configurable);
* size quota per tenant;
* cleanup-loop через :class:`TaskRegistry` (см. R-V15-11);
* audit-event на каждое создание workspace'а.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from src.backend.core.ai.errors import (
    WorkspaceQuotaExceededError,
    WorkspaceTTLExpiredError,
)

__all__ = ("AIWorkspaceManager", "WorkspaceHandle")

_logger = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS: float = 7 * 24 * 3600
DEFAULT_QUOTA_BYTES: int = 500 * 1024 * 1024
DEFAULT_CLEANUP_INTERVAL_SECONDS: float = 6 * 3600


@dataclass(frozen=True, slots=True)
class WorkspaceHandle:
    """Уникальный хэндл выданного AI-workspace.

    Attributes:
        tenant: Идентификатор тенанта.
        session_id: Уникальный session-id (UUID4).
        path: Абсолютный путь каталога workspace'а.
        created_at: Unix-timestamp создания.
    """

    tenant: str
    session_id: str
    path: Path
    created_at: float


AuditCallback = Callable[[dict[str, object]], None]
"""Сигнатура audit-callback'а: принимает event dict, ничего не возвращает."""


@dataclass(slots=True)
class _TenantUsage:
    bytes_used: int = 0
    sessions: dict[str, WorkspaceHandle] = field(default_factory=dict)


class AIWorkspaceManager:
    """Менеджер AI-workspace'ов с TTL + quota + cleanup-loop.

    Args:
        root: Корень AI-workspace ($AI_WORKSPACE).
        ttl_seconds: TTL отдельного session-workspace.
        per_tenant_quota_bytes: Лимит на сумму размеров живых workspaces
            одного тенанта.
        cleanup_interval_seconds: Период cleanup-loop (отдельный
            ``asyncio.Task``).
        audit: Опц. callback на ``create_new``/``cleanup`` события.
    """

    def __init__(
        self,
        *,
        root: Path,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        per_tenant_quota_bytes: int = DEFAULT_QUOTA_BYTES,
        cleanup_interval_seconds: float = DEFAULT_CLEANUP_INTERVAL_SECONDS,
        audit: AuditCallback | None = None,
    ) -> None:
        self._root = root
        self._ttl = ttl_seconds
        self._quota = per_tenant_quota_bytes
        self._cleanup_interval = cleanup_interval_seconds
        self._audit = audit
        self._usage: dict[str, _TenantUsage] = {}
        self._lock = asyncio.Lock()
        self._cleanup_task: asyncio.Task[None] | None = None
        self._closed: bool = False

    @property
    def root(self) -> Path:
        """Корневой каталог workspace'ов (для диагностики)."""
        return self._root

    async def create_new(
        self, *, tenant: str, artifact_hint: str | None = None
    ) -> WorkspaceHandle:
        """Выдать новый изолированный workspace тенанту.

        Args:
            tenant: Идентификатор тенанта.
            artifact_hint: Опц. подсказка для именования (для удобства
                чтения логов; не влияет на безопасность).

        Raises:
            WorkspaceQuotaExceededError: Tenant превысил per-tenant
                quota суммой размеров живых workspaces.
        """
        async with self._lock:
            if self._closed:
                raise RuntimeError("AIWorkspaceManager закрыт")

            usage = self._usage.setdefault(tenant, _TenantUsage())
            if usage.bytes_used > self._quota:
                raise WorkspaceQuotaExceededError(
                    tenant=tenant,
                    used_bytes=usage.bytes_used,
                    quota_bytes=self._quota,
                )

            session_id = uuid.uuid4().hex
            session_path = self._root / tenant / session_id
            session_path.mkdir(parents=True, exist_ok=False)

            handle = WorkspaceHandle(
                tenant=tenant,
                session_id=session_id,
                path=session_path,
                created_at=time.time(),
            )
            usage.sessions[session_id] = handle

            self._emit_audit(
                {
                    "event": "ai_workspace.create_new",
                    "tenant": tenant,
                    "session_id": session_id,
                    "path": str(session_path),
                    "artifact_hint": artifact_hint,
                }
            )
            return handle

    def assert_alive(self, handle: WorkspaceHandle) -> None:
        """Проверить, что workspace ещё не TTL-expired.

        Raises:
            WorkspaceTTLExpiredError: TTL истёк — caller обязан запросить
                новый workspace через :meth:`create_new`.
        """
        age = time.time() - handle.created_at
        if age > self._ttl:
            raise WorkspaceTTLExpiredError(
                session_id=handle.session_id,
                age_seconds=age,
                ttl_seconds=self._ttl,
            )

    def add_used_bytes(self, tenant: str, delta: int) -> None:
        """Учесть запись ``delta`` байт в usage-counter тенанта.

        Вызывается :class:`AIFsFacade` после каждого ``create_new``.
        """
        usage = self._usage.setdefault(tenant, _TenantUsage())
        usage.bytes_used += delta

    async def cleanup_expired(self) -> int:
        """Удалить все workspaces со старше TTL.

        Returns:
            Число удалённых workspaces.
        """
        removed = 0
        now = time.time()
        async with self._lock:
            for tenant, usage in list(self._usage.items()):
                for session_id, handle in list(usage.sessions.items()):
                    if now - handle.created_at <= self._ttl:
                        continue
                    try:
                        size_freed = _dir_size(handle.path)
                        shutil.rmtree(handle.path, ignore_errors=True)
                    except OSError as exc:
                        _logger.warning(
                            "ai_workspace.cleanup_failed: %s (%s)",
                            handle.path,
                            exc,
                        )
                        continue
                    usage.sessions.pop(session_id, None)
                    usage.bytes_used = max(0, usage.bytes_used - size_freed)
                    removed += 1
                    self._emit_audit(
                        {
                            "event": "ai_workspace.cleanup",
                            "tenant": tenant,
                            "session_id": session_id,
                            "freed_bytes": size_freed,
                        }
                    )
        return removed

    async def start_cleanup_loop(
        self,
        *,
        task_factory: Callable[..., asyncio.Task[None]] | None = None,
    ) -> None:
        """Запустить периодический cleanup через TaskRegistry.

        Args:
            task_factory: Опц. фабрика task'ов (обычно
                ``TaskRegistry.create_task``); если ``None`` —
                используется raw ``asyncio.create_task``. Параметр
                сигнатуры: ``task_factory(coro, *, name)``.
        """
        if self._cleanup_task is not None and not self._cleanup_task.done():
            return

        async def _loop() -> None:
            try:
                while not self._closed:
                    await asyncio.sleep(self._cleanup_interval)
                    try:
                        await self.cleanup_expired()
                    except Exception as exc:  # noqa: BLE001
                        _logger.warning("ai_workspace.cleanup_error: %s", exc)
            except asyncio.CancelledError:
                raise

        if task_factory is None:
            self._cleanup_task = asyncio.create_task(
                _loop(), name="ai-workspace-cleanup"
            )
        else:
            self._cleanup_task = task_factory(_loop(), name="ai-workspace-cleanup")

    async def shutdown(self) -> None:
        """Остановить cleanup-loop (TaskRegistry-aware)."""
        self._closed = True
        task = self._cleanup_task
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001, S110
                pass

    def _emit_audit(self, event: dict[str, object]) -> None:
        if self._audit is None:
            return
        try:
            self._audit(event)
        except Exception as exc:  # noqa: BLE001
            _logger.debug("ai_workspace audit emission failed: %s", exc)


def _dir_size(path: Path) -> int:
    """Возвращает суммарный размер всех файлов в каталоге (без follow_symlinks)."""
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
