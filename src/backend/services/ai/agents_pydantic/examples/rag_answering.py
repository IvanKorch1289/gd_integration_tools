"""RagAnsweringAgent — пример typed-агента с RAG-tool."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from src.backend.services.ai.agents_pydantic.base import BasePydanticAgent

__all__ = ("RagAnswer", "RagAnsweringAgent")


class RagAnswer(BaseModel):
    """Ответ агента: текст + список цитат (chunk_id)."""

    answer: str = Field(description="Финальный ответ модели")
    citations: list[str] = Field(
        default_factory=list, description="Список chunk_id из RAG-индекса"
    )


class RagAnsweringAgent(BasePydanticAgent[RagAnswer]):
    """RAG-агент: вызывает ``RAGService.search`` как tool, возвращает structured."""

    result_type = RagAnswer

    def __init__(
        self, rag_service: Any | None = None, top_k: int = 5, **kwargs: object
    ) -> None:
        super().__init__(
            system_prompt=(
                "You are a Russian-language RAG assistant. "
                "Use the `retrieve` tool to fetch context, then answer."
            ),
            **kwargs,  
        )
        self._rag_service = rag_service
        self._top_k = top_k

    def _ensure_rag(self) -> Any:
        if self._rag_service is not None:
            return self._rag_service
        from src.backend.core.di.app_state import get_app_ref

        app = get_app_ref()
        rag = getattr(app.state, "rag_service", None) if app is not None else None
        if rag is None:
            raise RuntimeError("RagAnsweringAgent: app.state.rag_service отсутствует.")
        self._rag_service = rag
        return rag

    async def retrieve(
        self, query: str, namespace: str | None = None
    ) -> list[dict[str, Any]]:
        """Tool-функция: возвращает top_k chunks из RAG."""
        rag = self._ensure_rag()
        return await rag.search(query, top_k=self._top_k, namespace=namespace)
