"""MCP domain namespaces (ADR-0070, S27 W4).

Каждый namespace — логическая группировка MCP tools по domain:
- credit: кредитные процессы (credit.* actions)
- analytics: аналитика и метрики (analytics.*, metrics.* actions)
- system: инфраструктурные tools (system.*, tech.*, health.* actions)

Namespace-группировка позволяет:
- Раздельный deploy и ownership per team
- Fine-grained capability-gate per namespace
- Per-namespace rate-limit и audit
"""

from __future__ import annotations

__all__ = (
    "CREDIT_NAMESPACE",
    "ANALYTICS_NAMESPACE",
    "SYSTEM_NAMESPACE",
    "AI_NAMESPACE",
    "MCPNamespace",
    "get_namespace_for_action",
    "list_namespaces",
)

from dataclasses import dataclass


@dataclass(slots=True)
class MCPNamespace:
    """Logical grouping of MCP tools по domain (ADR-0070 §1).

    Attributes:
        name: Уникальный идентификатор namespace ("credit", "analytics", "system").
        description: Human-readable описание namespace.
        action_prefixes: Список prefix-действий, принадлежащих namespace
            (напр. ["credit.", "credit_score."] для credit).
        capabilities_required: Список capability, необходимых для доступа к namespace.
    """

    name: str
    description: str
    action_prefixes: tuple[str, ...] = ()
    capabilities_required: tuple[str, ...] = ()


CREDIT_NAMESPACE = MCPNamespace(
    name="credit",
    description="Кредитные процессы: scoring, decisioning, underwriting.",
    action_prefixes=("credit.",),
    capabilities_required=("mcp.gateway.invoke.credit",),
)

ANALYTICS_NAMESPACE = MCPNamespace(
    name="analytics",
    description="Аналитика и метрики: reporting, dashboards, data export.",
    action_prefixes=("analytics.", "metrics."),
    capabilities_required=("mcp.gateway.invoke.analytics",),
)

SYSTEM_NAMESPACE = MCPNamespace(
    name="system",
    description="Инфраструктурные tools: system, tech, health, admin.",
    action_prefixes=("system.", "tech.", "health.", "admin."),
    capabilities_required=("mcp.gateway.invoke.system",),
)

# S32 W3: AI namespace для AI/RAG/ML actions
AI_NAMESPACE = MCPNamespace(
    name="ai",
    description="AI/RAG/ML actions: search, chat, agent, embeddings, model registry.",
    action_prefixes=("ai.", "ml.", "rag.", "embed."),
    capabilities_required=("mcp.gateway.invoke.ai",),
)


def get_namespace_for_action(action_name: str) -> MCPNamespace | None:
    """Возвращает MCPNamespace для action или None если не найден.

    Проверяет action_name против ``action_prefixes`` каждого namespace.
    Первый matching namespace возвращается.

    Args:
        action_name: Полное имя action (напр. "credit.score.calculate").

    Returns:
        MCPNamespace или None если action не принадлежит ни одному namespace.
    """
    for ns in (CREDIT_NAMESPACE, ANALYTICS_NAMESPACE, SYSTEM_NAMESPACE, AI_NAMESPACE):
        for prefix in ns.action_prefixes:
            if action_name.startswith(prefix):
                return ns
    return None


def list_namespaces() -> list[MCPNamespace]:
    """Возвращает список всех defined namespaces.

    Returns:
        Список [credit, analytics, system, ai] namespaces.
    """
    return [CREDIT_NAMESPACE, ANALYTICS_NAMESPACE, SYSTEM_NAMESPACE, AI_NAMESPACE]
