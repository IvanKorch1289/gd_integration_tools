"""Поисковые @agent_tool: RAG + AgentMemory (Wave 8.5)."""

from __future__ import annotations

from typing import Any

from src.services.ai.tools import agent_tool


@agent_tool(
    name="rag_search",
    description="Семантический поиск в RAG (top-k chunks по namespace).",
)
async def rag_search(
    query: str, top_k: int = 5, namespace: str | None = None
) -> list[dict[str, Any]]:
    """Возвращает top-k ближайших chunks из RAG-индекса.

    Args:
        query: Поисковый запрос.
        top_k: Количество результатов.
        namespace: Опциональный namespace.

    Returns:
        Список ``{id, document, metadata, distance}``.
    """
    from src.services.ai.rag_service import get_rag_service

    return await get_rag_service().search(query, top_k=top_k, namespace=namespace)


@agent_tool(
    name="rag_augment",
    description="Генерирует augmented-prompt с RAG-контекстом для LLM.",
)
async def rag_augment(
    query: str, system_prompt: str = "", top_k: int = 5, namespace: str | None = None
) -> str:
    """Возвращает финальный prompt: system + RAG-context + query."""
    from src.services.ai.rag_service import get_rag_service

    return await get_rag_service().augment_prompt(
        query, system_prompt=system_prompt, top_k=top_k, namespace=namespace
    )


@agent_tool(
    name="agent_memory_recall",
    description="Возвращает conversation/scratchpad/facts по session_id.",
)
async def agent_memory_recall(session_id: str) -> dict[str, Any]:
    """Загружает все 3 ресурса AgentMemory для данной сессии.

    Args:
        session_id: ID сессии.

    Returns:
        Словарь с ключами ``conversation``, ``scratchpad``, ``facts``.
    """
    from src.services.ai.agent_memory import get_agent_memory_service

    return await get_agent_memory_service().load_memory(session_id)
