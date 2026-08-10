"""Protocol + dataclass для AgentSandbox (core-level контракт).

Реализации остаются в ``services.ai.agent_sandbox``.
DSL и core импортируют Protocol отсюда — без layer violation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

__all__ = ("AgentSandbox", "AgentSandboxResult")


@dataclass(frozen=True, slots=True)
class AgentSandboxResult:
    """Результат выполнения агентского шага в sandbox.

    Attributes:
        success: True если sandbox-выполнение завершилось без исключения.
        data: Словарь-результат (формат ``build_and_run_agent``) либо
            ``{"error": str}`` при ``success=False``.
        backend: Имя backend'а, который произвёл выполнение.

    """

    success: bool
    data: dict[str, Any]
    backend: str


@runtime_checkable
class AgentSandbox(Protocol):
    """Backend-agnostic sandbox для LangGraph ReAct-агента."""

    async def run_react(
        self,
        *,
        prompt: str,
        tool_actions: list[str],
        model: str,
        temperature: float,
        durable: bool,
        session_id: str | None,
    ) -> AgentSandboxResult:
        """Запустить ReAct-агента в sandbox."""
        ...
