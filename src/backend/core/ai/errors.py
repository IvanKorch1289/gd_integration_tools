"""Типизированные ошибки AI Safety subsystem (V15 R-V15-4)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = (
    "AIFsError",
    "AIWorkspaceError",
    "GuardResult",
    "GuardrailViolationError",
    "MCPToolError",
    "WorkspaceQuotaExceededError",
    "WorkspaceTTLExpiredError",
)


@dataclass(frozen=True, slots=True)
class GuardResult:
    """Результат одного guard check для audit-события.

    Attributes:
        guard_name: Идентификатор (``"llama_guard:safe_v3"``, ``"rebuff"``, etc.).
        verdict: Вердикт (``"passed"``, ``"blocked"``, ``"warned"``).
        categories: Срабоавшие категории при блокировке.
    """

    guard_name: str
    verdict: str
    categories: list[str] = field(default_factory=list)


class GuardrailViolationError(Exception):
    """Выходной guard заблокировал контент (Llama Guard / NeMo / Rebuff / Lakera).

    Attributes:
        guard_name: Идентификатор guard'а (``"llama_guard:safe_v3"``, etc.).
        flagged_categories: Категории нарушения
            (``["hate", "violence"]``).
        on_block: Поведение при блокировке (``"fail"`` | ``"dlq"`` | ``"warn"``).
        content: Заблокированный контент (не хранить raw PII).
    """

    def __init__(
        self,
        *,
        guard_name: str,
        flagged_categories: list[str],
        on_block: str = "fail",
        content: str = "",
    ) -> None:
        self.guard_name = guard_name
        self.flagged_categories = flagged_categories
        self.on_block = on_block
        self.content = content[:200] if content else ""  # truncate для логов
        super().__init__(
            f"Guard {guard_name!r} blocked content "
            f"(categories={flagged_categories}, on_block={on_block})"
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


class MCPToolError(Exception):
    """Normalized MCP tool execution error — no internal details leak."""

    def __init__(self, message: str = "Tool execution failed") -> None:
        self.message = message
        super().__init__(message)

    def to_dict(self) -> dict[str, Any]:
        return {"error": self.message}


class AIFsError(Exception):
    """Базовый класс ошибок :class:`AIFsFacade`."""


class FsForbiddenWriteError(AIFsError):
    """Попытка записи существующего файла или файла вне workspace."""

    def __init__(self, *, path: str, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"Forbidden write to {path!r}: {reason}")
