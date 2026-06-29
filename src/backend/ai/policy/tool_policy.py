"""Agent Tool Policy — per-agent tool permission gate.

S169: Provides whitelist/blacklist-based tool access control for AI agents.
Default-deny: any tool not explicitly allowed is denied.

Security properties:
    - Default-deny: unknown tools are DENY (no silent allow).
    - Deny list takes precedence over allow list.
    - Audit trail via ToolPermission.AUDIT for allowed tools when audit_all=True.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, PrivateAttr


class ToolPermission(str, Enum):
    """Результат проверки инструмента."""

    ALLOW = "allow"
    DENY = "deny"
    AUDIT = "audit"


class AgentToolPolicy(BaseModel):
    """Политика доступа агента к инструментам.

    Attributes:
        agent_id: Уникальный идентификатор агента.
        allowed_tools: Список разрешённых tool names. Пустой список = ничего не разрешено.
        denied_tools: Список запрещённых tool names (приоритет над allowed).
        audit_all: Если True — разрешённые инструменты возвращают AUDIT,
            а не ALLOW (для логирования).
        max_tool_calls_per_run: Максимальное число вызовов tool за один run.
            При превышении — последний вызов получает DENY.
    """

    agent_id: str = Field(..., description="Уникальный ID агента")
    allowed_tools: list[str] = Field(
        default_factory=list, description="Разрешённые tool names"
    )
    denied_tools: list[str] = Field(
        default_factory=list,
        description="Явно запрещённые tool names (приоритетнее allowed)",
    )
    audit_all: bool = Field(
        default=True,
        description="Разрешённые инструменты возвращают AUDIT (для логирования)",
    )
    max_tool_calls_per_run: int = Field(
        default=50, ge=1, description="Максимум tool calls за один run"
    )

    # Transient counter — not serialized, reset per run.
    _tool_call_count: int = PrivateAttr(default=0)

    def check(self, tool_name: str) -> ToolPermission:
        """Проверяет разрешение на выполнение инструмента.

        Args:
            tool_name: Имя tool из LangGraph tool call.

        Returns:
            ToolPermission.DENY — запрещён явно или не в allowed.
            ToolPermission.ALLOW — разрешён (и не audit_all).
            ToolPermission.AUDIT — разрешён + audit_all=True.
        """
        if tool_name in self.denied_tools:
            return ToolPermission.DENY

        if self._tool_call_count >= self.max_tool_calls_per_run:
            return ToolPermission.DENY

        if tool_name in self.allowed_tools:
            self._tool_call_count += 1
            return ToolPermission.AUDIT if self.audit_all else ToolPermission.ALLOW

        # Default-deny: явно не разрешён = DENY.
        return ToolPermission.DENY

    def reset_run(self) -> None:
        """Сбросить счётчик вызовов для нового run.

        Вызывать в начале каждого agent execution cycle.
        """
        self._tool_call_count = 0

    def is_allowed(self, tool_name: str) -> bool:
        """Удобный shortcut — возвращает True только для ALLOW (не AUDIT).

        Используйте когда нужен bool, а не enum.
        """
        result = self.check(tool_name)
        return result == ToolPermission.ALLOW


    def check(self, tool_name: str) -> Any:
        """Проверить tool — возвращает ToolPermission (default-deny, D269).

        Args:
            tool_name: Имя tool.

        Returns:
            ToolPermission.ALLOW если разрешён, иначе ToolPermission.DENY.
        """
        from src.backend.core.logging import get_logger
        _logger = get_logger("ai.tool_policy")
        if tool_name in self.allowed_tools:
            _logger.debug("ai.tool_policy.allow tool=%s", tool_name)
            return "allow"
        if tool_name in self.denied_tools:
            _logger.warning(
                "ai.tool_policy.deny tool=%s reason=denied", tool_name
            )
            return "deny"
        # Default-deny для unknown tools
        _logger.warning(
            "ai.tool_policy.deny tool=%s reason=unknown_default_deny", tool_name
        )
        return "deny"

    def enforce(self, tool_name: str) -> bool:
        """Проверить и audit-log — возвращает True если разрешён (D269)."""
        result = self.check(tool_name)
        return result == "allow"
