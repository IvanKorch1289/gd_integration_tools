"""Типизированные ошибки AI Safety subsystem (V15 R-V15-4)."""

from __future__ import annotations

__all__ = (
    "AIFsError",
    "AIWorkspaceError",
    "WorkspaceQuotaExceededError",
    "WorkspaceTTLExpiredError",
)


class AIWorkspaceError(Exception):
    """Базовый класс ошибок workspace-подсистемы."""


class WorkspaceQuotaExceededError(AIWorkspaceError):
    """Tenant превысил per-tenant size quota.

    Attributes:
        tenant: Идентификатор тенанта.
        used_bytes: Текущее потребление.
        quota_bytes: Лимит из конфигурации.
    """

    def __init__(self, *, tenant: str, used_bytes: int, quota_bytes: int) -> None:
        self.tenant = tenant
        self.used_bytes = used_bytes
        self.quota_bytes = quota_bytes
        super().__init__(
            f"Tenant {tenant!r} workspace quota exceeded: "
            f"{used_bytes} / {quota_bytes} bytes"
        )


class WorkspaceTTLExpiredError(AIWorkspaceError):
    """Workspace со старше TTL — записи в него запрещены.

    Attributes:
        session_id: Идентификатор session-workspace'а.
        age_seconds: Возраст в секундах.
        ttl_seconds: Лимит TTL.
    """

    def __init__(
        self, *, session_id: str, age_seconds: float, ttl_seconds: float
    ) -> None:
        self.session_id = session_id
        self.age_seconds = age_seconds
        self.ttl_seconds = ttl_seconds
        super().__init__(
            f"Workspace {session_id!r} TTL expired: "
            f"{age_seconds:.0f}s > {ttl_seconds:.0f}s"
        )


class AIFsError(Exception):
    """Базовый класс ошибок :class:`AIFsFacade`."""


class FsForbiddenWriteError(AIFsError):
    """Попытка записи существующего файла или файла вне workspace."""

    def __init__(self, *, path: str, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"Forbidden write to {path!r}: {reason}")
